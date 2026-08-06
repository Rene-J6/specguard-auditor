import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
import unicodedata
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
CANONICAL_FIELDS = (
    "text", "label", "category", "has_modal", "source", "generation_batch"
)
REQUIREMENT_CATEGORIES = {
    "functional_modal",
    "functional_no_modal",
    "nonfunctional_modal",
    "nonfunctional_no_modal",
    "poorly_written_requirement",
}
NON_REQUIREMENT_CATEGORIES = {
    "background", "purpose", "definition", "implementation_note",
    "hard_negative_modal",
}
CATEGORY_LABELS = {
    **{category: 1 for category in REQUIREMENT_CATEGORIES},
    **{category: 0 for category in NON_REQUIREMENT_CATEGORIES},
}
REQUIRED_MODAL_CATEGORIES = {
    "functional_modal", "nonfunctional_modal", "hard_negative_modal"
}
FORBIDDEN_MODAL_CATEGORIES = {
    "functional_no_modal", "nonfunctional_no_modal"
}
REVIEW_FIELDS = (
    "text", "text_sha256", "proposed_label", "category", "has_modal", "source",
    "generation_batch", "decision", "corrected_label", "corrected_category",
    "notes",
)


def _has_modal_keyword(text):
    from app.requirement_detector import has_modal_keyword
    return has_modal_keyword(text)


def validate_sample(sample):
    if set(sample) != set(CANONICAL_FIELDS):
        raise ValueError(f"Sample fields must be exactly {CANONICAL_FIELDS}.")

    text = sample["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string.")
    word_count = len(text.split())
    if len(text) > 1500 or not 3 <= word_count <= 200:
        raise ValueError("text must contain 3-200 words and at most 1500 characters.")

    label = sample["label"]
    if isinstance(label, bool) or label not in (0, 1):
        raise ValueError("label must be 0 or 1.")
    category = sample["category"]
    if CATEGORY_LABELS.get(category) != label:
        raise ValueError("category does not match label.")
    if not isinstance(sample["has_modal"], bool):
        raise ValueError("has_modal must be a boolean.")
    if sample["has_modal"] != _has_modal_keyword(text):
        raise ValueError("has_modal does not match the keyword baseline.")
    if category in REQUIRED_MODAL_CATEGORIES and not sample["has_modal"]:
        raise ValueError("modal category must contain a baseline modal phrase.")
    if category in FORBIDDEN_MODAL_CATEGORIES and sample["has_modal"]:
        raise ValueError("no-modal category cannot contain a baseline modal phrase.")
    if sample["source"] != "synthetic":
        raise ValueError("source must be synthetic.")
    if not isinstance(sample["generation_batch"], str) or not sample["generation_batch"]:
        raise ValueError("generation_batch is required.")

    return {field: sample[field] for field in CANONICAL_FIELDS}


def normalized_fingerprint(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deduplicate_samples(samples, encoder=None, threshold=0.95):
    kept = []
    fingerprints = {}
    exact_removed = 0
    for sample in samples:
        fingerprint = normalized_fingerprint(sample["text"])
        if fingerprint in fingerprints:
            if fingerprints[fingerprint]["label"] != sample["label"]:
                raise ValueError("Exact duplicate has conflicting labels.")
            exact_removed += 1
            continue
        fingerprints[fingerprint] = sample
        kept.append(sample)

    near_removed = 0
    if encoder is not None and len(kept) > 1:
        embeddings = np.asarray(encoder.encode(
            [sample["text"] for sample in kept],
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        ), dtype=float)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-12)
        similarities = embeddings @ embeddings.T
        removed = set()
        for left in range(len(kept)):
            if left in removed:
                continue
            for right in range(left + 1, len(kept)):
                if right in removed or similarities[left, right] < threshold:
                    continue
                if kept[left]["label"] != kept[right]["label"]:
                    raise ValueError("Near duplicate has conflicting labels.")
                removed.add(right)
                near_removed += 1
        kept = [sample for index, sample in enumerate(kept) if index not in removed]

    return kept, {
        "exact_duplicates_removed": exact_removed,
        "near_duplicates_removed": near_removed,
    }


def split_by_batch(samples, train_batch_count=28, validation_batch_count=6):
    batches = OrderedDict()
    for sample in samples:
        batches.setdefault(sample["generation_batch"], []).append(sample)
    ordered = sorted(batches.items())
    required = train_batch_count + validation_batch_count
    if len(ordered) < required:
        raise ValueError(f"Need {required} complete batches, found {len(ordered)}.")
    train_ids = {batch_id for batch_id, _ in ordered[:train_batch_count]}
    validation_ids = {
        batch_id for batch_id, _ in ordered[train_batch_count:required]
    }
    train = [row for row in samples if row["generation_batch"] in train_ids]
    validation = [
        row for row in samples if row["generation_batch"] in validation_ids
    ]
    return train, validation


def split_balanced_by_batch(samples, train_count=1400, validation_count=300):
    if train_count % 2 or validation_count % 2:
        raise ValueError("Split sizes must be even for 50/50 class balance.")
    batches = OrderedDict()
    for sample in samples:
        batches.setdefault(sample["generation_batch"], []).append(sample)
    ordered = sorted(batches.items())

    def collect(start, target):
        quota = target // 2
        pool = []
        index = start
        counts = Counter()
        while index < len(ordered) and (counts[0] < quota or counts[1] < quota):
            _, batch = ordered[index]
            pool.extend(batch)
            counts.update(row["label"] for row in batch)
            index += 1
        if counts[0] < quota or counts[1] < quota:
            raise ValueError("Not enough batch-grouped samples for balanced splits.")
        selected = []
        selected_counts = Counter()
        for row in pool:
            if selected_counts[row["label"]] < quota:
                selected.append(row)
                selected_counts[row["label"]] += 1
        return selected, index

    train, next_batch = collect(0, train_count)
    validation, _ = collect(next_batch, validation_count)
    return train, validation


def find_cross_split_near_duplicates(left, right, encoder, threshold=0.95):
    if not left or not right:
        return []
    texts = [row["text"] for row in left] + [row["text"] for row in right]
    embeddings = np.asarray(encoder.encode(
        texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
    ), dtype=float)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, 1e-12)
    left_embeddings = embeddings[:len(left)]
    right_embeddings = embeddings[len(left):]
    similarities = left_embeddings @ right_embeddings.T
    return [
        {
            "left_text": left[left_index]["text"],
            "right_text": right[right_index]["text"],
            "similarity": float(similarities[left_index, right_index]),
        }
        for left_index in range(len(left))
        for right_index in range(len(right))
        if similarities[left_index, right_index] >= threshold
    ]


def prepare_test_candidates(
    candidates, development, encoder, minimum_count=300, threshold=0.95
):
    candidates, duplicate_summary = deduplicate_samples(
        candidates, encoder=encoder, threshold=threshold
    )
    leakage = find_cross_split_near_duplicates(
        development, candidates, encoder, threshold=threshold
    )
    leaked_fingerprints = {
        normalized_fingerprint(pair["right_text"]) for pair in leakage
    }
    candidates = [
        row for row in candidates
        if normalized_fingerprint(row["text"]) not in leaked_fingerprints
    ]
    if minimum_count % 2:
        raise ValueError("minimum_count must be even.")
    counts = Counter(row["label"] for row in candidates)
    quota = minimum_count // 2
    if counts[0] < quota or counts[1] < quota:
        raise ValueError("Not enough independent balanced test candidates.")
    return candidates, {
        "candidate_count": len(candidates),
        "class_counts": dict(counts),
        "development_near_duplicates_removed": len(leaked_fingerprints),
        **duplicate_summary,
    }


def validate_generation_batch(samples, expected_per_category=5):
    expected_total = expected_per_category * len(CATEGORY_LABELS)
    if len(samples) != expected_total:
        raise ValueError(f"Batch must contain {expected_total} samples.")
    counts = Counter(sample["category"] for sample in samples)
    if any(counts[category] != expected_per_category for category in CATEGORY_LABELS):
        raise ValueError("Batch category balance is invalid.")
    if Counter(sample["label"] for sample in samples) != {
        0: expected_total // 2, 1: expected_total // 2
    }:
        raise ValueError("Batch class balance is invalid.")


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=path.parent
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_jsonl(samples, path):
    content = "".join(
        json.dumps(sample, ensure_ascii=False) + "\n" for sample in samples
    )
    _atomic_write(path, content)


def read_jsonl_files(input_dir):
    rows = []
    for path in sorted(Path(input_dir).rglob("*.jsonl")):
        rows.extend(read_jsonl(path))
    return rows


def read_jsonl(path):
    rows = []
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    rows.append(validate_sample(json.loads(line)))
                except (json.JSONDecodeError, ValueError) as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def read_development_splits(input_dir):
    input_dir = Path(input_dir)
    return read_jsonl(input_dir / "train.jsonl") + read_jsonl(
        input_dir / "validation.jsonl"
    )


def write_review_csv(samples, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for raw_sample in samples:
            sample = validate_sample(raw_sample)
            writer.writerow({
                "text": sample["text"],
                "text_sha256": hashlib.sha256(
                    sample["text"].encode("utf-8")
                ).hexdigest(),
                "proposed_label": sample["label"],
                "category": sample["category"],
                "has_modal": str(sample["has_modal"]).lower(),
                "source": sample["source"],
                "generation_batch": sample["generation_batch"],
                "decision": "",
                "corrected_label": "",
                "corrected_category": "",
                "notes": "",
            })


def freeze_reviewed_test(review_path, test_path, manifest_path, target_count=300):
    with Path(review_path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    pending = [row for row in rows if row["decision"].strip().lower() not in {
        "accept", "relabel", "reject"
    }]
    if pending:
        raise ValueError(f"{len(pending)} review rows are still pending.")

    reviewed = []
    for row in rows:
        if hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != row.get(
            "text_sha256"
        ):
            raise ValueError("Review text was modified; regenerate the review CSV.")
        decision = row["decision"].strip().lower()
        if decision == "reject":
            continue
        if decision == "relabel":
            if row["corrected_label"].strip() not in {"0", "1"}:
                raise ValueError("Relabel rows require corrected_label 0 or 1.")
            label = int(row["corrected_label"])
            category = row["corrected_category"].strip()
        else:
            label = int(row["proposed_label"])
            category = row["category"]
        reviewed.append(validate_sample({
            "text": row["text"],
            "label": label,
            "category": category,
            "has_modal": _has_modal_keyword(row["text"]),
            "source": "synthetic",
            "generation_batch": row["generation_batch"],
        }))

    if target_count % 2:
        raise ValueError("target_count must be even.")
    quota = target_count // 2
    selected = []
    counts = Counter()
    for row in reviewed:
        if counts[row["label"]] < quota:
            selected.append(row)
            counts[row["label"]] += 1
    if counts != {0: quota, 1: quota}:
        raise ValueError("Not enough reviewed samples to create a balanced test set.")

    write_jsonl(selected, test_path)
    test_path = Path(test_path)
    digest = hashlib.sha256(test_path.read_bytes()).hexdigest()
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "test_count": len(selected),
        "class_counts": {"0": counts[0], "1": counts[1]},
        "test_sha256": digest,
    }
    _atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
    return selected


def load_encoder(model_name="sentence-transformers/all-MiniLM-L6-v2"):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name, device="cpu")


def prepare_development(input_dir, output_dir, model_name):
    samples = read_jsonl_files(input_dir)
    batches = OrderedDict()
    for sample in samples:
        batches.setdefault(sample["generation_batch"], []).append(sample)
    complete = []
    rejected_batches = {}
    for batch_id, batch in sorted(batches.items()):
        try:
            validate_generation_batch(batch)
            complete.extend(batch)
        except ValueError as error:
            rejected_batches[batch_id] = str(error)
    encoder = load_encoder(model_name)
    complete, duplicate_summary = deduplicate_samples(
        complete, encoder=encoder
    )
    train, validation = split_balanced_by_batch(complete)
    if len(train) != 1400 or len(validation) != 300:
        raise ValueError("Prepared split sizes must be 1400 train and 300 validation.")
    leakage = find_cross_split_near_duplicates(train, validation, encoder)
    if leakage:
        raise ValueError(
            f"Found {len(leakage)} near-duplicate pairs across train and validation."
        )

    output_dir = Path(output_dir)
    train_path = output_dir / "train.jsonl"
    validation_path = output_dir / "validation.jsonl"
    write_jsonl(train, train_path)
    write_jsonl(validation, validation_path)
    summary = {
        "train_count": len(train),
        "validation_count": len(validation),
        "train_class_counts": dict(Counter(row["label"] for row in train)),
        "validation_class_counts": dict(Counter(row["label"] for row in validation)),
        "rejected_batches": rejected_batches,
        **duplicate_summary,
    }
    _atomic_write(output_dir / "dataset_summary.json",
                  json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Prepare requirement detection data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    development = subparsers.add_parser("prepare-development")
    development.add_argument("--input-dir", required=True)
    development.add_argument(
        "--output-dir", default=PROJECT_ROOT / "data" / "requirement_detection"
    )
    development.add_argument(
        "--model", default="sentence-transformers/all-MiniLM-L6-v2"
    )

    review = subparsers.add_parser("export-review")
    review.add_argument("--input-dir", required=True)
    review.add_argument(
        "--development-dir",
        default=PROJECT_ROOT / "data" / "requirement_detection",
    )
    review.add_argument(
        "--model", default="sentence-transformers/all-MiniLM-L6-v2"
    )
    review.add_argument(
        "--output", default=PROJECT_ROOT / "data" / "requirement_detection" /
        "test_review.csv"
    )

    freeze = subparsers.add_parser("freeze-test")
    freeze.add_argument(
        "--review", default=PROJECT_ROOT / "data" / "requirement_detection" /
        "test_review.csv"
    )
    freeze.add_argument(
        "--output", default=PROJECT_ROOT / "data" / "requirement_detection" /
        "test.jsonl"
    )
    freeze.add_argument(
        "--manifest", default=PROJECT_ROOT / "data" / "requirement_detection" /
        "dataset_manifest.json"
    )

    args = parser.parse_args()
    if args.command == "prepare-development":
        print(json.dumps(prepare_development(
            args.input_dir, args.output_dir, args.model
        ), indent=2))
    elif args.command == "export-review":
        rows = read_jsonl_files(args.input_dir)
        development_rows = read_development_splits(args.development_dir)
        rows, summary = prepare_test_candidates(
            rows, development_rows, load_encoder(args.model)
        )
        write_review_csv(rows, args.output)
        _atomic_write(
            Path(args.output).parent / "test_candidate_summary.json",
            json.dumps(summary, indent=2) + "\n",
        )
        print(f"Wrote {len(rows)} review candidates to {args.output}")
    else:
        rows = freeze_reviewed_test(args.review, args.output, args.manifest)
        print(f"Frozen {len(rows)} reviewed test samples.")


if __name__ == "__main__":
    main()
