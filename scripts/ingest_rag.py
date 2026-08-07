import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
from langchain_chroma import Chroma
from langchain_core.documents import Document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.retrieval import (  # noqa: E402
    CANDIDATE_DB_DIR,
    COLLECTION_NAME,
    KNOWLEDGE_BASE_DIR,
    create_bge_embeddings,
)


SOURCE_MANIFEST = KNOWLEDGE_BASE_DIR / "sources.json"
INDEX_MANIFEST = KNOWLEDGE_BASE_DIR / "index_manifest.json"
MAX_CHARS = 1500
HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,6})\s+(.+)$")
NUMBER_ONLY_RE = re.compile(r"^\d+(?:\.\d+){1,6}$")


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


def _normalized_line(line):
    return re.sub(r"\s+", " ", line).strip()


def source_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_source_manifest(path=SOURCE_MANIFEST):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources.json must contain a non-empty sources list.")

    filenames = set()
    for source in sources:
        if set(source) != {"filename", "standard", "parser"}:
            raise ValueError("Each source needs filename, standard, and parser only.")
        if source["parser"] not in {"numbered", "section"}:
            raise ValueError(f"Unsupported parser for {source['filename']}.")
        if not source["filename"] or not source["standard"]:
            raise ValueError("Source filename and standard cannot be empty.")
        key = source["filename"].casefold()
        if key in filenames:
            raise ValueError(f"Duplicate source filename: {source['filename']}")
        filenames.add(key)

    actual = {path.name.casefold() for path in KNOWLEDGE_BASE_DIR.glob("*.pdf")}
    missing = [source["filename"] for source in sources
               if source["filename"].casefold() not in actual]
    unlisted = sorted(actual - filenames)
    if missing:
        raise FileNotFoundError(f"Missing knowledge PDFs: {', '.join(missing)}")
    if unlisted:
        raise ValueError(f"PDFs missing from sources.json: {', '.join(unlisted)}")
    return sorted(sources, key=lambda item: item["filename"].casefold())


def extract_pages(path):
    with pdfplumber.open(path) as pdf:
        return [PageText(index + 1, page.extract_text() or "")
                for index, page in enumerate(pdf.pages)]


def remove_repeated_margins(pages):
    page_lines = [[_normalized_line(line) for line in page.text.splitlines()
                   if _normalized_line(line)] for page in pages]
    counts = Counter()
    for lines in page_lines:
        counts.update(set(lines[:3] + lines[-3:]))
    minimum = max(3, math.ceil(len(pages) * 0.25))
    repeated = {line for line, count in counts.items() if count >= minimum}
    return [PageText(page.page, "\n".join(
        line for line in lines if line not in repeated
    )) for page, lines in zip(pages, page_lines)]


def _numbered_heading(line):
    match = HEADING_RE.match(line)
    if not match or not re.search(r"[A-Za-z]", match.group(2)):
        return None
    if len(match.group(2)) > 120 or match.group(2).endswith("."):
        return None
    return match.group(1), match.group(2).strip()


def _section_heading(line):
    if not 2 <= len(line) <= 100 or line.endswith((".", ";", ",")):
        return None
    words = re.findall(r"[A-Za-z][A-Za-z0-9&/-]*", line)
    if not 1 <= len(words) <= 12:
        return None
    uppercase = line.upper() == line and any(char.isalpha() for char in line)
    title_case = sum(word[0].isupper() for word in words) / len(words) >= 0.8
    return line if uppercase or title_case else None


def _split_long_text(heading, body, max_chars=MAX_CHARS):
    prefix = heading.strip()
    text = " ".join(part.strip() for part in body if part.strip())
    full = f"{prefix}\n{text}".strip()
    if len(full) <= max_chars:
        return [full]

    sentences = re.split(r"(?<=[.!?;])\s+", text)
    expanded = []
    for sentence in sentences:
        while len(prefix) + len(sentence) + 1 > max_chars:
            limit = max_chars - len(prefix) - 1
            split_at = sentence.rfind(" ", 0, limit)
            split_at = split_at if split_at > 0 else limit
            expanded.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            expanded.append(sentence)
    sentences = expanded
    parts = []
    current = []
    for sentence in sentences:
        candidate = " ".join(current + [sentence]).strip()
        if current and len(prefix) + len(candidate) + 1 > max_chars:
            parts.append(f"{prefix}\n{' '.join(current)}")
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        parts.append(f"{prefix}\n{' '.join(current)}")
    return parts


def parse_pages(pages, parser):
    pages = remove_repeated_margins(pages)
    sections = []
    current = None
    pending_clause = None

    for page in pages:
        for line in page.text.splitlines():
            line = _normalized_line(line)
            if not line:
                continue
            if parser == "numbered" and NUMBER_ONLY_RE.fullmatch(line):
                pending_clause = (line, page.page)
                continue
            numbered = _numbered_heading(line) if parser == "numbered" else None
            if parser == "numbered" and pending_clause:
                if len(line) <= 120 and re.search(r"[A-Za-z]", line):
                    numbered = (pending_clause[0], line)
                pending_clause = None
            section = _section_heading(line) if parser == "section" else None
            heading = numbered or (("", section) if section else None)
            if heading:
                if current and current["body"]:
                    sections.append(current)
                current = {
                    "clause": heading[0],
                    "title": heading[1],
                    "page": page.page,
                    "page_end": page.page,
                    "body": [],
                }
            elif current:
                current["body"].append(line)
                current["page_end"] = page.page

    if current and current["body"]:
        sections.append(current)

    if sections:
        return sections

    # Controlled fallback for a document with no detectable headings.
    return [{
        "clause": "",
        "title": f"Page {page.page}",
        "page": page.page,
        "page_end": page.page,
        "body": [_normalized_line(line) for line in page.text.splitlines()
                 if _normalized_line(line)],
    } for page in pages if page.text.strip()]


def build_source_chunks(pdf_path, source):
    digest = source_hash(pdf_path)
    documents = []
    ids = []
    for section in parse_pages(extract_pages(pdf_path), source["parser"]):
        heading = " ".join(filter(None, [section["clause"], section["title"]]))
        parts = _split_long_text(heading, section["body"])
        for index, content in enumerate(parts, start=1):
            metadata = {
                "standard": source["standard"],
                "clause": section["clause"],
                "title": section["title"],
                "source": source["filename"],
                "page": section["page"],
                "page_end": section["page_end"],
                "parent_clause_id": f"{source['standard']}:{section['clause'] or section['title']}",
                "part_index": index,
                "part_count": len(parts),
                "source_sha256": digest,
            }
            fingerprint = "\n".join([
                digest,
                section["clause"],
                section["title"],
                str(index),
                re.sub(r"\s+", " ", content).casefold(),
            ])
            ids.append(hashlib.sha256(fingerprint.encode("utf-8")).hexdigest())
            documents.append(Document(page_content=content, metadata=metadata))
    return documents, ids, digest


def prepare_documents(manifest_path=SOURCE_MANIFEST):
    documents = []
    ids = []
    seen_ids = set()
    source_details = []
    for source in load_source_manifest(manifest_path):
        path = KNOWLEDGE_BASE_DIR / source["filename"]
        print(f"Reading {path.name}...")
        started = time.perf_counter()
        source_documents, source_ids, digest = build_source_chunks(path, source)
        duplicate_count = 0
        for document, chunk_id in zip(source_documents, source_ids):
            if chunk_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(chunk_id)
            documents.append(document)
            ids.append(chunk_id)
        source_details.append({
            "filename": source["filename"],
            "standard": source["standard"],
            "sha256": digest,
            "chunk_count": len(source_documents) - duplicate_count,
            "exact_duplicates_removed": duplicate_count,
            "parse_seconds": round(time.perf_counter() - started, 2),
        })
        print(
            f"  {len(source_documents) - duplicate_count} chunks; "
            f"{duplicate_count} exact duplicates removed."
        )
    if not documents:
        raise ValueError("No knowledge-base chunks were produced.")
    return documents, ids, source_details


def _validate_candidate_target(path):
    resolved = Path(path).resolve()
    if resolved.parent != KNOWLEDGE_BASE_DIR.resolve() or resolved.name != "chroma_candidate":
        raise ValueError("Candidate index must be data/knowledge_base/chroma_candidate.")
    return resolved


def build_candidate_index(output=CANDIDATE_DB_DIR):
    output = _validate_candidate_target(output)
    documents, ids, sources = prepare_documents()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    print(f"Embedding {len(documents)} clause-aware chunks with BGE-M3 on CPU...")
    store = Chroma.from_documents(
        documents=documents,
        ids=ids,
        embedding=create_bge_embeddings(),
        collection_name=COLLECTION_NAME,
        persist_directory=str(output),
        collection_configuration={"hnsw": {"space": "cosine"}},
    )
    count = store._collection.count()
    if count != len(documents):
        raise RuntimeError(f"Candidate index has {count} rows; expected {len(documents)}.")

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collection_name": COLLECTION_NAME,
        "embedding_model": "BAAI/bge-m3",
        "embedding_normalized": True,
        "distance_metric": "cosine",
        "chunk_max_characters": MAX_CHARS,
        "chunk_count": count,
        "sources": sources,
        "status": "candidate",
    }
    INDEX_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Candidate index ready at {output} with {count} chunks.")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Build the Phase 2B candidate RAG index.")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Parse and validate sources without loading BGE-M3 or writing Chroma.",
    )
    args = parser.parse_args()
    if args.prepare_only:
        documents, ids, sources = prepare_documents()
        print(json.dumps({"chunk_count": len(documents), "id_count": len(ids),
                          "sources": sources}, indent=2))
        return
    build_candidate_index()


if __name__ == "__main__":
    main()
