import csv
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_rag_generation import (
    JudgeScores,
    judge_case,
    normalize_score,
    prepare_case,
    representative_failures,
    score_agreement,
    select_expert_ids,
    summarize_judges,
    summarize_judgements,
    write_expert_review,
)


def case(index, category="functional", expected_match=True):
    return {
        "id": f"case_{index:03d}",
        "category": category,
        "expected_match": expected_match,
        "requirement": f"Requirement {index}",
        "retrieved_standard": "ISO 1",
        "retrieved_clause": "2.1",
        "retrieved_context": "The requirement shall be verifiable.",
        "evidence": "ISO 1 - Clause 2.1\nThe requirement shall be verifiable.",
        "compliance_status": "partially_compliant",
        "issue_types": "not_measurable",
        "evidence_excerpt": "The requirement shall be verifiable.",
        "explanation": "The requirement has no measurable target.",
        "suggested_rewrite": "The response shall complete within two seconds.",
    }


class FakeResponse:
    def __init__(self, parsed=None, text=""):
        self.parsed = parsed
        self.text = text


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.last_kwargs = None

    def generate_content(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


class RagGenerationEvaluationTests(unittest.TestCase):
    def test_score_validation_and_normalization(self):
        schema = JudgeScores.model_json_schema()
        self.assertEqual(schema["properties"]["faithfulness_score"]["minimum"], 0)
        self.assertEqual(schema["properties"]["faithfulness_score"]["maximum"], 2)
        self.assertEqual(normalize_score(0), 0)
        self.assertEqual(normalize_score(1), 0.5)
        self.assertEqual(normalize_score(2), 1)
        for invalid in (-1, 3, 1.0, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_score(invalid)

    def test_expert_selection_is_deterministic_and_covers_every_category(self):
        cases = []
        for category_index in range(9):
            for row_index in range(6):
                cases.append(case(
                    category_index * 10 + row_index,
                    category=f"category_{category_index}",
                ))
        first = select_expert_ids(cases)
        second = select_expert_ids(cases)
        selected = [row for row in cases if row["id"] in first]

        self.assertEqual(first, second)
        self.assertEqual(len(first), 15)
        self.assertEqual(len({row["category"] for row in selected}), 9)

    def test_summary_reports_all_cases_as_one_group(self):
        rows = [
            {**case(1), "faithfulness_score": 2, "answer_relevance_score": 1,
             "error": ""},
            {**case(2),
             "faithfulness_score": 0, "answer_relevance_score": 2, "error": ""},
            {**case(3), "faithfulness_score": None,
             "answer_relevance_score": None, "error": "network error"},
        ]

        summary = summarize_judgements(rows)

        self.assertEqual(summary["all"]["case_count"], 3)
        self.assertEqual(summary["all"]["error_count"], 1)
        self.assertEqual(summary["all"]["faithfulness"]["mean_normalized"], 0.5)
        self.assertEqual(
            summary["all"]["answer_relevance"]["score_counts"],
            {"0": 0, "1": 1, "2": 1},
        )
        self.assertEqual(set(summary), {"all"})

    def test_two_judges_are_summarized_separately_with_agreement(self):
        rows = []
        for model, scores in (("judge-a", (0, 1, 2)), ("judge-b", (0, 2, 2))):
            for index, score in enumerate(scores):
                rows.append({
                    **case(index), "judge_model": model,
                    "faithfulness_score": score, "answer_relevance_score": score,
                    "error": "",
                })

        summary = summarize_judges(rows)

        self.assertEqual(set(summary["by_model"]), {"judge-a", "judge-b"})
        pair = summary["judge_agreement"]["judge-a vs judge-b"]
        self.assertEqual(pair["case_count"], 3)
        self.assertEqual(pair["faithfulness"]["exact_agreement"], 2 / 3)

    def test_agreement_reports_exact_and_quadratic_weighted_kappa(self):
        agreement = score_agreement([0, 1, 2], [0, 1, 2])
        self.assertEqual(agreement["exact_agreement"], 1)
        self.assertEqual(agreement["quadratic_weighted_kappa"], 1)

    def test_representative_failures_only_include_zero_scores(self):
        rows = [
            {**case(1), "faithfulness_score": 0, "answer_relevance_score": 2,
             "faithfulness_reason": "Unsupported.", "answer_relevance_reason": "Direct.",
             "unsupported_claims": ["invented"], "error": ""},
            {**case(2), "faithfulness_score": 2, "answer_relevance_score": 0,
             "faithfulness_reason": "Supported.", "answer_relevance_reason": "Unrelated.",
             "unsupported_claims": [], "error": ""},
        ]

        failures = representative_failures(rows)

        self.assertEqual([row["id"] for row in failures["faithfulness"]], ["case_001"])
        self.assertEqual(
            [row["id"] for row in failures["answer_relevance"]], ["case_002"]
        )

    def test_judge_retries_one_malformed_response(self):
        valid = JudgeScores(
            faithfulness_score=2,
            answer_relevance_score=1,
            faithfulness_reason="Supported.",
            answer_relevance_reason="Partly direct.",
            unsupported_claims=[],
        )
        client = FakeClient([FakeResponse(text="not json"), FakeResponse(parsed=valid)])

        result = judge_case(client, "judge-model", case(1))

        self.assertEqual(result, valid)
        self.assertEqual(client.models.calls, 2)
        contents = client.models.last_kwargs["contents"]
        self.assertIn('"requirement"', contents)
        self.assertIn('"evidence"', contents)
        self.assertIn('"explanation"', contents)
        self.assertIn('"suggested_rewrite"', contents)
        self.assertIn("Do not expect the rewrite to repair", contents)
        self.assertNotIn('"compliance_status"', contents)
        self.assertNotIn('"issue_types"', contents)

    def test_retrieval_metadata_mismatch_stops_evaluation(self):
        row = {
            "id": "case_001",
            "category": "functional",
            "expected_standard": "ISO 1",
            "requirement": "The system shall work.",
            "retrieved_standard": "ISO 1",
            "retrieved_clause": "2.1",
            "structured_status": "compliant",
            "structured_issue_types": "none",
            "structured_evidence": "Evidence.",
            "structured_explanation": "Supported.",
            "structured_rewrite": "The system shall work.",
        }
        candidate = {
            "standard": "ISO 2", "clause": "3.1", "source": "source.pdf",
            "score": 0.5, "text": "Other evidence.",
        }

        with self.assertRaisesRegex(ValueError, "no longer matches"):
            prepare_case(row, candidate)

    def test_blinded_sheet_excludes_judge_scores_and_preserves_human_scores(self):
        categories = [f"category_{index}" for index in range(9)]
        cases = [case(index, categories[index % 9]) for index in range(18)]
        selected_ids = tuple(row["id"] for row in cases[:10])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "expert.csv"
            write_expert_review(cases, path, selected_ids)
            with path.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 10)
            self.assertNotIn("faithfulness_score", rows[0])
            self.assertNotIn("compliance_status", rows[0])
            self.assertEqual(
                [field for field in rows[0] if field not in {
                    "id", "category", "expert_faithfulness_score",
                    "expert_answer_relevance_score", "expert_comments",
                    "researcher_adjudicated_faithfulness_score",
                    "researcher_adjudicated_answer_relevance_score", "researcher_notes",
                }],
                ["requirement", "evidence", "explanation", "suggested_rewrite"],
            )
            rows[0]["expert_faithfulness_score"] = "2"
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            write_expert_review(cases, path, selected_ids)
            with path.open(encoding="utf-8-sig", newline="") as source:
                updated = list(csv.DictReader(source))
            self.assertEqual(updated[0]["expert_faithfulness_score"], "2")


if __name__ == "__main__":
    unittest.main()
