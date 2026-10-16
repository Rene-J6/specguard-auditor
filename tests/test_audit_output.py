import json
import unittest

from app.audit_output import (
    AuditValidationError,
    parse_stored_audit,
    run_structured_audit,
    validate_generated_audit,
)
from scripts.evaluate_audit_output import summarize_evaluation


REQUIREMENT = "The system shall return search results quickly."
EVIDENCE = {
    "standard": "ISO/IEC/IEEE 29148:2018",
    "clause": "5.2.5",
    "title": "Characteristics of individual requirements",
    "source": "ISO IEC IEEE 29148.pdf",
    "text": "Requirements shall be stated with measurable effectiveness criteria.",
}


def generated(**overrides):
    value = {
        "compliance_status": "non_compliant",
        "issue_types": ["not_measurable"],
        "evidence_id": "E1",
        "evidence": "Requirements shall be stated with measurable effectiveness criteria.",
        "explanation": "The word 'quickly' has no measurable response-time target.",
        "suggested_rewrite": "The system shall return search results within two seconds.",
    }
    value.update(overrides)
    return json.dumps(value)


class StructuredAuditTests(unittest.TestCase):
    def test_valid_output_maps_reference_from_retrieved_evidence(self):
        result = validate_generated_audit(generated(), REQUIREMENT, EVIDENCE)

        self.assertEqual(result.validation_status, "validated")
        self.assertEqual(result.standard_reference.standard, EVIDENCE["standard"])
        self.assertEqual(result.standard_reference.clause, EVIDENCE["clause"])

    def test_invalid_json_missing_field_and_enum_are_rejected(self):
        cases = [
            "```json\n{}\n```",
            generated(explanation=None),
            generated(compliance_status="mostly_compliant"),
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(AuditValidationError):
                validate_generated_audit(value, REQUIREMENT, EVIDENCE)

    def test_issue_rules_reject_none_mixes_duplicates_and_wrong_status(self):
        cases = [
            generated(issue_types=["none", "ambiguous"]),
            generated(issue_types=["ambiguous", "ambiguous"]),
            generated(compliance_status="compliant", issue_types=["ambiguous"]),
            generated(compliance_status="non_compliant", issue_types=[]),
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(AuditValidationError):
                validate_generated_audit(value, REQUIREMENT, EVIDENCE)

    def test_grounding_accepts_wrapped_text_and_rejects_wrong_evidence(self):
        wrapped = dict(EVIDENCE, text="Requirements shall be stated\nwith measurable effectiveness criteria.")
        validate_generated_audit(generated(), REQUIREMENT, wrapped)

        with self.assertRaises(AuditValidationError) as error:
            validate_generated_audit(
                generated(evidence="Requirements shall follow ISO 27001."),
                REQUIREMENT,
                EVIDENCE,
            )
        self.assertEqual(error.exception.code, "ungrounded_evidence")

    def test_unknown_evidence_id_and_unsupported_citation_are_rejected(self):
        with self.assertRaises(AuditValidationError):
            validate_generated_audit(generated(evidence_id="E2"), REQUIREMENT, EVIDENCE)
        with self.assertRaises(AuditValidationError) as error:
            validate_generated_audit(
                generated(explanation="ISO 27001 requires a two-second response time."),
                REQUIREMENT,
                EVIDENCE,
            )
        self.assertEqual(error.exception.code, "unsupported_reference")

    def test_compliant_and_insufficient_evidence_rules(self):
        compliant = generated(
            compliance_status="compliant",
            issue_types=["none"],
            suggested_rewrite=REQUIREMENT,
        )
        validate_generated_audit(compliant, REQUIREMENT, EVIDENCE)

        insufficient = generated(
            compliance_status="insufficient_evidence",
            issue_types=[],
            evidence_id=None,
            evidence="",
            explanation="The supplied evidence does not support this assessment.",
            suggested_rewrite=REQUIREMENT,
        )
        result = validate_generated_audit(insufficient, REQUIREMENT, EVIDENCE)
        self.assertIsNone(result.standard_reference)

    def test_one_retry_then_success(self):
        outputs = iter(["not json", generated()])
        run = run_structured_audit(REQUIREMENT, EVIDENCE, lambda messages: next(outputs))

        self.assertEqual(run.attempts, 2)
        self.assertEqual(run.result.validation_status, "validated")
        self.assertEqual(run.errors, ["invalid_json"])

    def test_controlled_repair_normalizes_json_without_another_generation(self):
        invalid = generated(
            compliance_status="compliant",
            issue_types=[],
            evidence="Paraphrased evidence that is not present in E1.",
            explanation="The requirement is clear and measurable.",
            suggested_rewrite="A changed requirement.",
        )
        run = run_structured_audit(REQUIREMENT, EVIDENCE, lambda messages: invalid)

        self.assertEqual(run.attempts, 1)
        self.assertTrue(run.repair_applied)
        self.assertEqual(run.result.issue_types, ["none"])
        self.assertEqual(run.result.evidence, EVIDENCE["text"])
        self.assertEqual(run.result.suggested_rewrite, REQUIREMENT)

    def test_controlled_repair_accepts_known_python_dict_and_legacy_shapes(self):
        python_dict = (
            "{'compliance_status': 'partially_compliant', "
            "'issue_types': ['incomplete'], 'evidence_id': null, "
            "'evidence': 'The requirement is missing a condition.', "
            "'suggested_rewrite': 'The system shall respond within two seconds.'}"
        )
        legacy = (
            "### Analysis\nThe requirement is vague and incomplete.\n\n"
            "### Suggested Rewrite\nThe system shall respond within two seconds."
        )

        repaired_dict = run_structured_audit(
            REQUIREMENT, EVIDENCE, lambda messages: python_dict
        )
        repaired_legacy = run_structured_audit(
            REQUIREMENT, EVIDENCE, lambda messages: legacy
        )

        self.assertTrue(repaired_dict.repair_applied)
        self.assertEqual(repaired_dict.result.compliance_status, "partially_compliant")
        self.assertEqual(repaired_dict.result.explanation, "The requirement is missing a condition.")
        self.assertTrue(repaired_legacy.repair_applied)
        self.assertEqual(repaired_legacy.result.issue_types, ["ambiguous", "incomplete"])

    def test_second_failure_returns_safe_result(self):
        run = run_structured_audit(REQUIREMENT, EVIDENCE, lambda messages: "not json")

        self.assertEqual(run.attempts, 2)
        self.assertEqual(run.result.validation_status, "safe_failure")
        self.assertEqual(run.result.compliance_status, "insufficient_evidence")
        self.assertEqual(run.result.suggested_rewrite, REQUIREMENT)

    def test_missing_retrieval_skips_generation(self):
        called = False

        def generate_text(messages):
            nonlocal called
            called = True

        run = run_structured_audit(REQUIREMENT, None, generate_text)

        self.assertFalse(called)
        self.assertEqual(run.attempts, 0)
        self.assertEqual(run.result.compliance_status, "insufficient_evidence")

    def test_stored_parser_supports_structured_and_legacy_outputs(self):
        structured = validate_generated_audit(generated(), REQUIREMENT, EVIDENCE)
        parsed = parse_stored_audit(structured.model_dump_json())
        legacy = parse_stored_audit(
            "### Analysis\nLegacy explanation.\n\n"
            "### Suggested Rewrite\nLegacy rewrite."
        )

        self.assertEqual(parsed["explanation"], structured.explanation)
        self.assertIsNotNone(parsed["audit"])
        self.assertEqual(legacy["explanation"], "Legacy explanation.")
        self.assertEqual(legacy["suggested_rewrite"], "Legacy rewrite.")
        self.assertIsNone(legacy["audit"])

    def test_evaluation_metrics_count_retries_failures_and_latency(self):
        rows = [
            {
                "structured_errors": [], "baseline_latency_ms": 10.0,
                "structured_latency_ms": 20.0, "structured_validation_status": "validated",
                "structured_first_json_valid": True, "structured_final_json_valid": True,
                "structured_attempts": 1, "baseline_parser_success": True,
            },
            {
                "structured_errors": ["invalid_json", "missing_field"],
                "baseline_latency_ms": 30.0, "structured_latency_ms": 60.0,
                "structured_validation_status": "safe_failure",
                "structured_first_json_valid": False, "structured_final_json_valid": True,
                "structured_attempts": 2, "baseline_parser_success": False,
            },
        ]

        metrics = summarize_evaluation(rows)

        self.assertEqual(metrics["baseline"]["parser_success_rate"], 0.5)
        self.assertEqual(metrics["structured"]["retry_rate"], 0.5)
        self.assertEqual(metrics["structured"]["safe_failure_rate"], 0.5)
        self.assertEqual(metrics["structured"]["missing_field_count"], 1)


if __name__ == "__main__":
    unittest.main()
