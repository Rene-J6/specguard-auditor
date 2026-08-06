import csv
import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np


def sample(text, label, category, batch="dev_batch_001", has_modal=False):
    return {
        "text": text,
        "label": label,
        "category": category,
        "has_modal": has_modal,
        "source": "synthetic",
        "generation_batch": batch,
    }


class FakeEncoder:
    def __init__(self, vectors):
        self.vectors = vectors

    def encode(self, texts, **kwargs):
        return np.asarray([self.vectors[text] for text in texts], dtype=float)


class RequirementDetectionDataTests(unittest.TestCase):
    def test_generated_rows_receive_local_labels_and_modal_metadata(self):
        from scripts.generate_requirement_detection_data import (
            GeneratedBatch, canonicalize_rows,
        )

        self.assertNotIn(
            "additionalProperties", json.dumps(GeneratedBatch.model_json_schema())
        )

        generated = []
        for category in (
            "functional_modal", "functional_no_modal", "nonfunctional_modal",
            "nonfunctional_no_modal", "poorly_written_requirement", "background",
            "purpose", "definition", "implementation_note", "hard_negative_modal",
        ):
            for index in range(5):
                modal = category in {"functional_modal", "nonfunctional_modal",
                                     "hard_negative_modal"}
                text = (
                    f"The system shall process item number {index}." if modal else
                    f"Users can process item number {index} in the portal."
                )
                generated.append({"text": text, "category": category})

        rows = canonicalize_rows(generated, "dev_batch_001")

        self.assertEqual(len(rows), 50)
        hard_negative = next(
            row for row in rows if row["category"] == "hard_negative_modal"
        )
        self.assertEqual(hard_negative["label"], 0)
        self.assertTrue(hard_negative["has_modal"])
        self.assertEqual(hard_negative["source"], "synthetic")

    def test_generator_only_skips_an_existing_valid_batch(self):
        from scripts.generate_requirement_detection_data import existing_batch_is_valid
        from scripts.prepare_requirement_detection_data import write_jsonl

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dev_batch_001.jsonl"
            rows = []
            categories = [
                "functional_modal", "functional_no_modal", "nonfunctional_modal",
                "nonfunctional_no_modal", "poorly_written_requirement", "background",
                "purpose", "definition", "implementation_note", "hard_negative_modal",
            ]
            for category in categories:
                for index in range(5):
                    modal = category in {
                        "functional_modal", "nonfunctional_modal", "hard_negative_modal"
                    }
                    rows.append(sample(
                        (f"The system shall process item number {index}." if modal else
                         f"Users can process item number {index} in the portal."),
                        1 if category in {
                            "functional_modal", "functional_no_modal",
                            "nonfunctional_modal", "nonfunctional_no_modal",
                            "poorly_written_requirement",
                        } else 0,
                        category,
                        "dev_batch_001",
                        modal,
                    ))
            write_jsonl(rows, path)
            self.assertTrue(existing_batch_is_valid(path, "dev_batch_001"))

            rows[-1]["text"] = "Stakeholders need to approve design changes."
            rows[-1]["has_modal"] = False
            write_jsonl(rows, path)
            self.assertFalse(existing_batch_is_valid(path, "dev_batch_001"))

    def test_gemini_client_has_a_finite_request_timeout(self):
        from scripts.generate_requirement_detection_data import create_gemini_client

        client = create_gemini_client("dummy-key")
        try:
            self.assertEqual(client._api_client._http_options.timeout, 120_000)
        finally:
            client.close()

    def test_validate_sample_rejects_extra_fields_and_wrong_modal_metadata(self):
        from scripts.prepare_requirement_detection_data import validate_sample

        valid = sample(
            "The system shall store records.",
            1,
            "functional_modal",
            has_modal=True,
        )
        self.assertEqual(validate_sample(valid), valid)

        with self.assertRaisesRegex(ValueError, "fields"):
            validate_sample({**valid, "unexpected": "value"})
        with self.assertRaisesRegex(ValueError, "has_modal"):
            validate_sample({**valid, "has_modal": False})
        with self.assertRaisesRegex(ValueError, "modal category"):
            validate_sample(sample(
                "Users can store records in the portal.",
                1,
                "functional_modal",
                has_modal=False,
            ))

    def test_exact_and_near_duplicates_keep_the_earliest_same_label_sample(self):
        from scripts.prepare_requirement_detection_data import deduplicate_samples

        exact = [
            sample("Users can reset passwords.", 1, "functional_no_modal"),
            sample("  users  CAN reset passwords. ", 1, "functional_no_modal"),
        ]
        kept, summary = deduplicate_samples(exact)
        self.assertEqual([row["text"] for row in kept], ["Users can reset passwords."])
        self.assertEqual(summary["exact_duplicates_removed"], 1)

        near = [
            sample("Users can reset passwords.", 1, "functional_no_modal"),
            sample("Customers can recover passwords.", 1, "functional_no_modal"),
            sample("This section describes the project background.", 0, "background"),
        ]
        encoder = FakeEncoder({
            near[0]["text"]: [1.0, 0.0],
            near[1]["text"]: [0.999, 0.001],
            near[2]["text"]: [0.0, 1.0],
        })
        kept, summary = deduplicate_samples(near, encoder=encoder, threshold=0.95)
        self.assertEqual(len(kept), 2)
        self.assertEqual(summary["near_duplicates_removed"], 1)

    def test_near_duplicate_label_conflict_stops_preparation(self):
        from scripts.prepare_requirement_detection_data import deduplicate_samples

        rows = [
            sample("Users can reset passwords.", 1, "functional_no_modal"),
            sample(
                "The team must reset passwords by Friday.",
                0,
                "hard_negative_modal",
                has_modal=True,
            ),
        ]
        encoder = FakeEncoder({row["text"]: [1.0, 0.0] for row in rows})

        with self.assertRaisesRegex(ValueError, "conflicting labels"):
            deduplicate_samples(rows, encoder=encoder, threshold=0.95)

    def test_split_by_batch_never_divides_a_generation_batch(self):
        from scripts.prepare_requirement_detection_data import split_by_batch

        rows = [
            sample("Requirement A", 1, "functional_no_modal", "dev_batch_001"),
            sample("Background A", 0, "background", "dev_batch_001"),
            sample("Requirement B", 1, "functional_no_modal", "dev_batch_002"),
            sample("Background B", 0, "background", "dev_batch_002"),
        ]

        train, validation = split_by_batch(rows, train_batch_count=1,
                                           validation_batch_count=1)
        self.assertEqual(
            {row["generation_batch"] for row in train}, {"dev_batch_001"}
        )
        self.assertEqual(
            {row["generation_batch"] for row in validation}, {"dev_batch_002"}
        )

    def test_cross_split_near_duplicate_is_reported(self):
        from scripts.prepare_requirement_detection_data import (
            find_cross_split_near_duplicates,
        )

        train = [sample(
            "Users can reset passwords.", 1, "functional_no_modal",
            "dev_batch_001",
        )]
        validation = [sample(
            "Customers can recover passwords.", 1, "functional_no_modal",
            "dev_batch_002",
        )]
        encoder = FakeEncoder({
            train[0]["text"]: [1.0, 0.0],
            validation[0]["text"]: [0.999, 0.001],
        })

        pairs = find_cross_split_near_duplicates(
            train, validation, encoder, threshold=0.95
        )

        self.assertEqual(pairs, [{
            "left_text": train[0]["text"],
            "right_text": validation[0]["text"],
            "similarity": pairs[0]["similarity"],
        }])
        self.assertGreaterEqual(pairs[0]["similarity"], 0.95)

    def test_test_candidates_exclude_development_near_duplicates(self):
        from scripts.prepare_requirement_detection_data import (
            prepare_test_candidates,
        )

        development = [sample(
            "Users can reset passwords.", 1, "functional_no_modal",
            "dev_batch_001",
        )]
        candidates = [
            sample("Customers can recover passwords.", 1,
                   "functional_no_modal", "test_batch_001"),
            sample("The portal displays account balances.", 1,
                   "functional_no_modal", "test_batch_001"),
            sample("This section describes existing operations.", 0,
                   "background", "test_batch_001"),
        ]
        encoder = FakeEncoder({
            development[0]["text"]: [1.0, 0.0],
            candidates[0]["text"]: [0.999, 0.001],
            candidates[1]["text"]: [0.0, 1.0],
            candidates[2]["text"]: [-1.0, 0.0],
        })

        kept, summary = prepare_test_candidates(
            candidates, development, encoder, minimum_count=2
        )

        self.assertEqual(
            [row["text"] for row in kept],
            [candidates[1]["text"], candidates[2]["text"]],
        )
        self.assertEqual(summary["development_near_duplicates_removed"], 1)

    def test_balanced_split_uses_extra_batches_after_deduplication(self):
        from scripts.prepare_requirement_detection_data import (
            split_balanced_by_batch,
        )

        rows = []
        for batch_index in range(1, 4):
            batch = f"dev_batch_{batch_index:03d}"
            rows.extend([
                sample(f"Requirement {batch} A", 1, "functional_no_modal", batch),
                sample(f"Requirement {batch} B", 1, "functional_no_modal", batch),
                sample(f"Background {batch} A", 0, "background", batch),
                sample(f"Background {batch} B", 0, "background", batch),
            ])
        rows.pop(0)  # Simulate a duplicate removed from the first batch.

        train, validation = split_balanced_by_batch(
            rows, train_count=4, validation_count=4
        )

        self.assertEqual(Counter(row["label"] for row in train), {0: 2, 1: 2})
        self.assertEqual(
            Counter(row["label"] for row in validation), {0: 2, 1: 2}
        )
        train_batches = {row["generation_batch"] for row in train}
        validation_batches = {row["generation_batch"] for row in validation}
        self.assertFalse(train_batches & validation_batches)

    def test_pending_review_cannot_freeze_test_set(self):
        from scripts.prepare_requirement_detection_data import (
            freeze_reviewed_test,
            write_review_csv,
        )

        rows = [
            sample("Users can reset passwords.", 1, "functional_no_modal",
                   "test_batch_001"),
            sample("This section describes the project.", 0, "background",
                   "test_batch_001"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_path = root / "review.csv"
            write_review_csv(rows, review_path)

            with self.assertRaisesRegex(ValueError, "pending"):
                freeze_reviewed_test(
                    review_path, root / "test.jsonl", root / "manifest.json",
                    target_count=2,
                )

    def test_development_reader_never_includes_the_frozen_test_file(self):
        from scripts.prepare_requirement_detection_data import (
            read_development_splits,
            write_jsonl,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_jsonl([sample(
                "Users can reset account passwords.", 1, "functional_no_modal"
            )], root / "train.jsonl")
            write_jsonl([sample(
                "This section describes existing operations.", 0, "background"
            )], root / "validation.jsonl")
            write_jsonl([sample(
                "The system shall archive records.", 1, "functional_modal",
                has_modal=True,
            )], root / "test.jsonl")

            rows = read_development_splits(root)

            self.assertEqual(len(rows), 2)
            self.assertNotIn("The system shall archive records.", {
                row["text"] for row in rows
            })

    def test_review_freeze_rejects_modified_text(self):
        from scripts.prepare_requirement_detection_data import (
            freeze_reviewed_test,
            write_review_csv,
        )

        rows = [
            sample("Users can reset account passwords.", 1,
                   "functional_no_modal", "test_batch_001"),
            sample("This section describes existing operations.", 0,
                   "background", "test_batch_001"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_path = root / "review.csv"
            write_review_csv(rows, review_path)
            with review_path.open(newline="", encoding="utf-8-sig") as handle:
                reviewed = list(csv.DictReader(handle))
            for row in reviewed:
                row["decision"] = "accept"
            reviewed[0]["text"] = "Users can change account passwords."
            with review_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=reviewed[0].keys())
                writer.writeheader()
                writer.writerows(reviewed)

            with self.assertRaisesRegex(ValueError, "text was modified"):
                freeze_reviewed_test(
                    review_path, root / "test.jsonl", root / "manifest.json",
                    target_count=2,
                )

    def test_reviewed_balanced_rows_freeze_to_jsonl_with_manifest_hash(self):
        from scripts.prepare_requirement_detection_data import (
            freeze_reviewed_test,
            write_review_csv,
        )

        rows = [
            sample("Users can reset passwords.", 1, "functional_no_modal",
                   "test_batch_001"),
            sample("This section describes the project.", 0, "background",
                   "test_batch_001"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_path = root / "review.csv"
            test_path = root / "test.jsonl"
            manifest_path = root / "manifest.json"
            write_review_csv(rows, review_path)

            with review_path.open(newline="", encoding="utf-8-sig") as handle:
                reviewed = list(csv.DictReader(handle))
            for row in reviewed:
                row["decision"] = "accept"
            with review_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=reviewed[0].keys())
                writer.writeheader()
                writer.writerows(reviewed)

            frozen = freeze_reviewed_test(
                review_path, test_path, manifest_path, target_count=2
            )

            self.assertEqual([row["label"] for row in frozen], [1, 0])
            expected_hash = hashlib.sha256(test_path.read_bytes()).hexdigest()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["test_sha256"], expected_hash)
            self.assertEqual(manifest["test_count"], 2)

    def test_threshold_selection_requires_ninety_percent_validation_recall(self):
        from scripts.train_requirement_detector import select_threshold

        selected = select_threshold(
            [1, 1, 1, 1, 0, 0],
            [0.45, 0.55, 0.65, 0.90, 0.45, 0.10],
        )
        self.assertEqual(selected["threshold"], 0.4)
        self.assertEqual(selected["recall"], 1.0)

        with self.assertRaisesRegex(ValueError, "90%"):
            select_threshold([1, 1, 0], [0.20, 0.30, 0.10])

    def test_training_rejects_a_test_dataset_path(self):
        from scripts.train_requirement_detector import ensure_training_path

        ensure_training_path(Path("data/requirement_detection/train.jsonl"))
        with self.assertRaisesRegex(ValueError, "test set"):
            ensure_training_path(Path("data/requirement_detection/test.jsonl"))

    def test_evaluation_metrics_and_slices_use_hand_checked_counts(self):
        from scripts.evaluate_requirement_detector import metric_bundle, slice_metrics

        metrics = metric_bundle([1, 1, 0, 0], [1, 0, 1, 0])
        self.assertEqual(metrics["confusion_matrix"], {
            "tn": 1, "fp": 1, "fn": 1, "tp": 1
        })
        self.assertEqual(metrics["accuracy"], 0.5)
        self.assertEqual(metrics["precision"], 0.5)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertEqual(metrics["f1"], 0.5)

        rows = [
            sample("Users can reset passwords.", 1, "functional_no_modal"),
            sample("Reports support CSV export.", 1, "functional_no_modal"),
            sample("The team must finish by Friday.", 0, "hard_negative_modal",
                   has_modal=True),
            sample("Managers should approve the schedule.", 0,
                   "hard_negative_modal", has_modal=True),
        ]
        slices = slice_metrics(rows, [1, 0, 1, 0])
        self.assertEqual(slices["requirements_without_modal"]["recall"], 0.5)
        self.assertEqual(
            slices["non_requirements_with_modal"]["specificity"], 0.5
        )
        self.assertEqual(slices["hard_negatives"]["specificity"], 0.5)

    def test_artifact_activation_requires_test_recall_and_baseline_improvement(self):
        from scripts.evaluate_requirement_detector import activate_artifact

        with tempfile.TemporaryDirectory() as temp_dir:
            metadata_path = Path(temp_dir) / "metadata.json"
            metadata_path.write_text(
                json.dumps({"enabled": False, "threshold": 0.4}),
                encoding="utf-8",
            )
            baseline = {"f1": 0.50, "recall": 0.60}
            failing = {"f1": 0.70, "recall": 0.89}
            passing = {"f1": 0.70, "recall": 0.90}

            self.assertFalse(activate_artifact(metadata_path, baseline, failing))
            self.assertFalse(json.loads(
                metadata_path.read_text(encoding="utf-8")
            )["enabled"])

            self.assertTrue(activate_artifact(metadata_path, baseline, passing))
            self.assertTrue(json.loads(
                metadata_path.read_text(encoding="utf-8")
            )["enabled"])


if __name__ == "__main__":
    unittest.main()
