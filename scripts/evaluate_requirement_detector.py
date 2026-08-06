import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.metrics import precision_score, recall_score

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from app.requirement_detector import keyword_is_requirement
from scripts.prepare_requirement_detection_data import (
    PROJECT_ROOT, _atomic_write, write_jsonl,
)


def metric_bundle(labels, predictions):
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "confusion_matrix": {
            "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)
        },
    }


def slice_metrics(samples, predictions):
    requirement_no_modal = [
        index for index, row in enumerate(samples)
        if row["label"] == 1 and not row["has_modal"]
    ]
    non_requirement_modal = [
        index for index, row in enumerate(samples)
        if row["label"] == 0 and row["has_modal"]
    ]
    hard_negatives = [
        index for index, row in enumerate(samples)
        if row["category"] == "hard_negative_modal"
    ]

    def recall_for(indices):
        return (sum(predictions[index] for index in indices) / len(indices)
                if indices else None)

    def specificity_for(indices):
        return (sum(not predictions[index] for index in indices) / len(indices)
                if indices else None)

    return {
        "requirements_without_modal": {
            "count": len(requirement_no_modal),
            "recall": recall_for(requirement_no_modal),
        },
        "non_requirements_with_modal": {
            "count": len(non_requirement_modal),
            "specificity": specificity_for(non_requirement_modal),
        },
        "hard_negatives": {
            "count": len(hard_negatives),
            "specificity": specificity_for(hard_negatives),
        },
    }


def activate_artifact(metadata_path, baseline_metrics, ml_metrics):
    if ml_metrics["recall"] < 0.90 or ml_metrics["f1"] <= baseline_metrics["f1"]:
        return False
    metadata_path = Path(metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["enabled"] = True
    metadata["activated_at"] = datetime.now(timezone.utc).isoformat()
    metadata["test_metrics"] = ml_metrics
    _atomic_write(metadata_path, json.dumps(metadata, indent=2) + "\n")
    return True


def _markdown_report(results):
    baseline = results["keyword_baseline"]
    ml = results["ml_classifier"]
    return (
        "# Requirement Detection Evaluation\n\n"
        "| Method | Accuracy | Precision | Recall | F1 | ms/sample |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        f"| Keyword baseline | {baseline['accuracy']:.4f} | "
        f"{baseline['precision']:.4f} | {baseline['recall']:.4f} | "
        f"{baseline['f1']:.4f} | {baseline['average_ms_per_sample']:.4f} |\n"
        f"| ML classifier | {ml['accuracy']:.4f} | {ml['precision']:.4f} | "
        f"{ml['recall']:.4f} | {ml['f1']:.4f} | "
        f"{ml['average_ms_per_sample']:.4f} |\n\n"
        f"Activation gate passed: {results['activation_gate_passed']}\n"
    )


def evaluate(test_path, manifest_path, artifact_dir, output_dir, activate=False):
    test_path = Path(test_path)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    digest = hashlib.sha256(test_path.read_bytes()).hexdigest()
    if digest != manifest["test_sha256"]:
        raise ValueError("Frozen test set hash does not match its manifest.")

    from scripts.prepare_requirement_detection_data import validate_sample
    samples = []
    with test_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                samples.append(validate_sample(json.loads(line)))
    if len(samples) != manifest["test_count"]:
        raise ValueError("Frozen test set count does not match its manifest.")

    artifact_dir = Path(artifact_dir)
    metadata = json.loads(
        (artifact_dir / "metadata.json").read_text(encoding="utf-8")
    )
    import joblib
    from sentence_transformers import SentenceTransformer
    encoder = SentenceTransformer(
        str(artifact_dir / "embedding_model"), device="cpu", local_files_only=True
    )
    classifier = joblib.load(artifact_dir / "classifier.joblib")
    texts = [row["text"] for row in samples]
    labels = [row["label"] for row in samples]

    encoder.encode(texts[:32], batch_size=32, normalize_embeddings=True,
                   show_progress_bar=False)
    start = time.perf_counter()
    for _ in range(3):
        baseline_predictions = [keyword_is_requirement(text) for text in texts]
    baseline_ms = (time.perf_counter() - start) * 1000 / (3 * len(texts))

    requirement_index = list(classifier.classes_).index(1)
    start = time.perf_counter()
    for _ in range(3):
        embeddings = encoder.encode(
            texts, batch_size=32, normalize_embeddings=True,
            show_progress_bar=False,
        )
        probabilities = classifier.predict_proba(embeddings)[:, requirement_index]
    ml_ms = (time.perf_counter() - start) * 1000 / (3 * len(texts))
    ml_predictions = [value >= metadata["threshold"] for value in probabilities]

    baseline_metrics = metric_bundle(labels, baseline_predictions)
    baseline_metrics["average_ms_per_sample"] = baseline_ms
    baseline_metrics["slices"] = slice_metrics(samples, baseline_predictions)
    ml_metrics = metric_bundle(labels, ml_predictions)
    ml_metrics["average_ms_per_sample"] = ml_ms
    ml_metrics["slices"] = slice_metrics(samples, ml_predictions)
    gate_passed = ml_metrics["recall"] >= 0.90 and ml_metrics["f1"] > baseline_metrics["f1"]

    false_positives = []
    false_negatives = []
    for row, predicted, probability in zip(samples, ml_predictions, probabilities):
        error = {**row, "confidence": float(probability)}
        if row["label"] == 0 and predicted:
            false_positives.append(error)
        elif row["label"] == 1 and not predicted:
            false_negatives.append(error)
    results = {
        "test_sha256": digest,
        "test_count": len(samples),
        "threshold": metadata["threshold"],
        "keyword_baseline": baseline_metrics,
        "ml_classifier": ml_metrics,
        "activation_gate_passed": gate_passed,
        "false_positive_count": len(false_positives),
        "false_negative_count": len(false_negatives),
    }

    output_dir = Path(output_dir)
    _atomic_write(output_dir / "evaluation.json",
                  json.dumps(results, indent=2) + "\n")
    _atomic_write(output_dir / "evaluation.md", _markdown_report(results))
    write_jsonl(false_positives, output_dir / "false_positives.jsonl")
    write_jsonl(false_negatives, output_dir / "false_negatives.jsonl")
    if activate and gate_passed:
        activate_artifact(
            artifact_dir / "metadata.json", baseline_metrics, ml_metrics
        )
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Compare keyword and ML requirement detectors."
    )
    parser.add_argument(
        "--test", default=PROJECT_ROOT / "data" / "requirement_detection" /
        "test.jsonl"
    )
    parser.add_argument(
        "--manifest", default=PROJECT_ROOT / "data" /
        "requirement_detection" / "dataset_manifest.json"
    )
    parser.add_argument(
        "--artifact-dir", default=PROJECT_ROOT / "models" /
        "requirement_detector"
    )
    parser.add_argument(
        "--output-dir", default=PROJECT_ROOT / "outputs" /
        "requirement_detection" / "evaluation"
    )
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    results = evaluate(
        args.test, args.manifest, args.artifact_dir, args.output_dir, args.activate
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
