import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeEncoder:
    def encode(self, texts, **kwargs):
        return [[index] for index, _ in enumerate(texts)]


class FakeClassifier:
    classes_ = [0, 1]

    def predict_proba(self, embeddings):
        probabilities = [0.39, 0.40, 0.87]
        return [[1 - probabilities[int(row[0])], probabilities[int(row[0])]]
                for row in embeddings]


class BrokenEncoder:
    def encode(self, texts, **kwargs):
        raise RuntimeError("embedding failure")


class FakeOcr:
    def readtext(self, processed_input, paragraph):
        return [
            [None, "The system shall store records."],
            [None, "Users can export reports."],
        ]


class RequirementDetectorTests(unittest.TestCase):
    def test_segment_document_preserves_order_and_structural_boundaries(self):
        from app.requirement_detector import segment_document

        text = (
            "Purpose\nThis document describes the portal.\n\n"
            "1. The system shall store audit records.\n"
            "2. Users can reset forgotten passwords\n"
            "- Response time must be under two seconds. Logging is required."
        )

        self.assertEqual(
            segment_document(text),
            [
                "Purpose This document describes the portal.",
                "1. The system shall store audit records.",
                "2. Users can reset forgotten passwords",
                "- Response time must be under two seconds.",
                "Logging is required.",
            ],
        )

    def test_segment_document_joins_wrapped_lines_without_rewriting_words(self):
        from app.requirement_detector import segment_document

        text = (
            "The system shall record every approved\n"
            "requirement in the audit log.\n"
            "Users can export the report."
        )

        self.assertEqual(
            segment_document(text),
            [
                "The system shall record every approved requirement in the audit log.",
                "Users can export the report.",
            ],
        )

    def test_clean_document_text_preserves_meaningful_newlines(self):
        from app.utils import clean_document_text

        cleaned = clean_document_text(
            "Heading\r\nThe  system\tshall work.\r\n\r\n\r\nUsers can log in."
        )

        self.assertEqual(
            cleaned,
            "Heading\nThe system shall work.\n\nUsers can log in.",
        )

    def test_image_ocr_preserves_paragraph_boundaries(self):
        from app.utils import extract_text_from_file

        with patch("app.utils.cv2.imread", return_value=None):
            extracted = extract_text_from_file("sample.png", "image/png", FakeOcr())

        self.assertEqual(
            extracted,
            "The system shall store records.\n\nUsers can export reports.",
        )

    def test_keyword_baseline_preserves_existing_substring_and_length_rules(self):
        from app.requirement_detector import has_modal_keyword, keyword_is_requirement

        self.assertTrue(keyword_is_requirement(
            "The development team must complete testing by Friday."
        ))
        self.assertFalse(keyword_is_requirement("Users can reset passwords."))
        self.assertFalse(keyword_is_requirement("It shall work"))
        self.assertTrue(has_modal_keyword("The team is willing to help."))

    def test_ml_predictions_use_requirement_probability_and_threshold(self):
        from app.requirement_detector import RequirementDetector

        detector = RequirementDetector(
            encoder=FakeEncoder(), classifier=FakeClassifier(), threshold=0.4
        )
        predictions = detector.predict_many(["first", "second", "third"])

        self.assertEqual(
            [item["is_requirement"] for item in predictions],
            [False, True, True],
        )
        self.assertEqual(
            [item["method"] for item in predictions],
            ["ml_classifier", "ml_classifier", "ml_classifier"],
        )
        self.assertAlmostEqual(predictions[0]["confidence"], 0.39)
        self.assertAlmostEqual(predictions[2]["confidence"], 0.87)

    def test_inference_failure_falls_back_for_the_entire_batch(self):
        from app.requirement_detector import RequirementDetector

        detector = RequirementDetector(
            encoder=BrokenEncoder(), classifier=FakeClassifier(), threshold=0.4
        )
        with self.assertLogs("app.requirement_detector", level="WARNING"):
            predictions = detector.predict_many([
                "The system shall store records.",
                "This section explains the project background.",
            ])

        self.assertEqual(
            [item["method"] for item in predictions],
            ["keyword_fallback", "keyword_fallback"],
        )
        self.assertEqual(
            [item["is_requirement"] for item in predictions], [True, False]
        )
        self.assertEqual(
            [item["confidence"] for item in predictions], [None, None]
        )

    def test_missing_or_disabled_artifact_loads_keyword_fallback(self):
        from app.requirement_detector import load_requirement_detector

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertLogs("app.requirement_detector", level="WARNING"):
                missing = load_requirement_detector(Path(temp_dir) / "missing")
            self.assertFalse(missing.uses_ml)

            disabled_dir = Path(temp_dir) / "disabled"
            disabled_dir.mkdir()
            (disabled_dir / "metadata.json").write_text(
                json.dumps({"enabled": False, "threshold": 0.4}),
                encoding="utf-8",
            )
            with self.assertLogs("app.requirement_detector", level="WARNING"):
                disabled = load_requirement_detector(disabled_dir)
            self.assertFalse(disabled.uses_ml)


if __name__ == "__main__":
    unittest.main()
