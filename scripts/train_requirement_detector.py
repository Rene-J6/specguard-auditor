import argparse
import hashlib
import importlib.metadata
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from scripts.prepare_requirement_detection_data import (
    PROJECT_ROOT, _atomic_write, read_jsonl,
)


THRESHOLDS = (0.4, 0.5, 0.6)


def ensure_training_path(path):
    path = Path(path)
    if "test" in path.stem.casefold():
        raise ValueError("The frozen test set cannot be used for training.")


def _metrics(labels, predictions):
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
    }


def select_threshold(labels, probabilities, minimum_recall=0.90):
    candidates = []
    for threshold in THRESHOLDS:
        predictions = [probability >= threshold for probability in probabilities]
        metrics = _metrics(labels, predictions)
        if metrics["recall"] >= minimum_recall:
            candidates.append({"threshold": threshold, **metrics})
    if not candidates:
        raise ValueError("No threshold achieved the required 90% validation recall.")
    return max(
        candidates,
        key=lambda candidate: (
            candidate["f1"], candidate["recall"], -candidate["threshold"]
        ),
    )


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def train_classifier(train_path, validation_path, artifact_dir, model_name):
    ensure_training_path(train_path)
    ensure_training_path(validation_path)
    # Read the files separately so no sibling test file can enter training.
    train_rows = read_jsonl(train_path)
    validation_rows = read_jsonl(validation_path)
    if not train_rows or not validation_rows:
        raise ValueError("Training and validation datasets must not be empty.")

    artifact_dir = Path(artifact_dir)
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise ValueError("Artifact directory must be empty before training.")

    from sentence_transformers import SentenceTransformer
    import joblib

    encoder = SentenceTransformer(model_name, device="cpu")
    train_embeddings = encoder.encode(
        [row["text"] for row in train_rows], batch_size=32,
        normalize_embeddings=True, show_progress_bar=True,
    )
    validation_embeddings = encoder.encode(
        [row["text"] for row in validation_rows], batch_size=32,
        normalize_embeddings=True, show_progress_bar=True,
    )
    classifier = LogisticRegression(
        class_weight="balanced", max_iter=1000, random_state=42
    )
    classifier.fit(train_embeddings, [row["label"] for row in train_rows])
    requirement_index = list(classifier.classes_).index(1)
    probabilities = classifier.predict_proba(validation_embeddings)[:, requirement_index]
    selection = select_threshold(
        [row["label"] for row in validation_rows], probabilities
    )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    encoder.save(str(artifact_dir / "embedding_model"))
    joblib.dump(classifier, artifact_dir / "classifier.joblib")
    metadata = {
        "format_version": 1,
        "enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": model_name,
        "device": "cpu",
        "threshold": selection["threshold"],
        "label_mapping": {"0": "Non-requirement", "1": "Requirement"},
        "train_count": len(train_rows),
        "validation_count": len(validation_rows),
        "train_class_counts": dict(Counter(row["label"] for row in train_rows)),
        "validation_class_counts": dict(
            Counter(row["label"] for row in validation_rows)
        ),
        "train_sha256": _file_hash(train_path),
        "validation_sha256": _file_hash(validation_path),
        "validation_metrics": selection,
        "versions": {
            "sentence-transformers": importlib.metadata.version(
                "sentence-transformers"
            ),
            "scikit-learn": importlib.metadata.version("scikit-learn"),
        },
    }
    _atomic_write(
        artifact_dir / "metadata.json", json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description="Train the requirement classifier.")
    parser.add_argument(
        "--train", default=PROJECT_ROOT / "data" / "requirement_detection" /
        "train.jsonl"
    )
    parser.add_argument(
        "--validation", default=PROJECT_ROOT / "data" /
        "requirement_detection" / "validation.jsonl"
    )
    parser.add_argument(
        "--artifact-dir", default=PROJECT_ROOT / "models" /
        "requirement_detector"
    )
    parser.add_argument(
        "--model", default="sentence-transformers/all-MiniLM-L6-v2"
    )
    args = parser.parse_args()
    metadata = train_classifier(
        args.train, args.validation, args.artifact_dir, args.model
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
