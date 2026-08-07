import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "data" / "knowledge_base"
ACTIVE_DB_DIR = KNOWLEDGE_BASE_DIR / "chroma_db"
CANDIDATE_DB_DIR = KNOWLEDGE_BASE_DIR / "chroma_candidate"
COLLECTION_NAME = "standards_v2"
DEFAULT_TOP_K = 5


def create_bge_embeddings(normalize_embeddings=True):
    """Load the existing BGE-M3 model locally on CPU with normalized output."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={"device": "cpu", "local_files_only": True},
        encode_kwargs={"normalize_embeddings": normalize_embeddings},
    )


def open_vectorstore(directory=ACTIVE_DB_DIR, embeddings=None):
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(directory),
        embedding_function=embeddings or create_bge_embeddings(),
    )


def open_runtime_vectorstore(directory=ACTIVE_DB_DIR):
    """Open the clause index when active, otherwise preserve the legacy index."""
    sqlite_path = Path(directory) / "chroma.sqlite3"
    has_clause_index = False
    if sqlite_path.exists():
        with sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True) as connection:
            has_clause_index = connection.execute(
                "SELECT 1 FROM collections WHERE name = ?", (COLLECTION_NAME,)
            ).fetchone() is not None
    if has_clause_index:
        return open_vectorstore(directory, create_bge_embeddings(True))

    from langchain_chroma import Chroma

    return Chroma(
        persist_directory=str(directory),
        embedding_function=create_bge_embeddings(False),
    )


def retrieve_standard_evidence(vectorstore, query, k=DEFAULT_TOP_K, threshold=None):
    """Return scored standard candidates without invoking the audit LLM."""
    rows = vectorstore.similarity_search_with_score(query, k=k)
    candidates = []
    for document, distance in rows:
        metadata = document.metadata or {}
        score = 1.0 - float(distance)
        if threshold is not None and score < threshold:
            continue
        source = Path(str(metadata.get("source", "Unknown"))).name
        candidates.append({
            "standard": metadata.get("standard", ""),
            "clause": metadata.get("clause", ""),
            "title": metadata.get("title", ""),
            "source": source,
            "page": metadata.get("page"),
            "page_end": metadata.get("page_end", metadata.get("page")),
            "text": document.page_content,
            "distance": float(distance),
            "score": score,
        })

    candidates.sort(key=lambda item: item["distance"])
    return {
        "query": query,
        "selected_clause": candidates[0] if candidates else None,
        "candidates": candidates,
        "method": "bge_m3_clause_retrieval",
    }
