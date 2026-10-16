import argparse
import csv
import gc
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audit_output import parse_stored_audit, run_structured_audit
from app.retrieval import retrieve_standard_evidence


DATA_DIR = PROJECT_ROOT / "data" / "audit_evaluation"
CASES_PATH = DATA_DIR / "cases.jsonl"


def _rate(count, total):
    return count / total if total else 0.0


def _p95(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def summarize_evaluation(rows):
    total = len(rows)
    errors = Counter(error for row in rows for error in row["structured_errors"])
    baseline_latencies = [row["baseline_latency_ms"] for row in rows]
    structured_latencies = [row["structured_latency_ms"] for row in rows]
    validated = sum(row["structured_validation_status"] == "validated" for row in rows)
    first_json = sum(row["structured_first_json_valid"] for row in rows)
    final_json = sum(row["structured_final_json_valid"] for row in rows)
    retried = sum(row["structured_attempts"] == 2 for row in rows)
    safe_failures = sum(row["structured_validation_status"] == "safe_failure" for row in rows)
    repaired = sum(row.get("structured_repair_applied", False) for row in rows)
    return {
        "sample_count": total,
        "baseline": {
            "parser_success_rate": _rate(
                sum(row["baseline_parser_success"] for row in rows), total
            ),
            "missing_rewrite_rate": _rate(
                sum(not row["baseline_parser_success"] for row in rows), total
            ),
            "average_latency_ms": sum(baseline_latencies) / total if total else 0.0,
            "p95_latency_ms": _p95(baseline_latencies),
            "json_metrics": None,
        },
        "structured": {
            "first_attempt_valid_json_rate": _rate(first_json, total),
            "final_attempt_valid_json_rate": _rate(final_json, total),
            "schema_validation_rate": _rate(validated, total),
            "missing_field_count": errors["missing_field"],
            "invalid_enum_count": errors["invalid_enum"],
            "grounding_failure_count": errors["ungrounded_evidence"],
            "unsupported_reference_count": errors["unsupported_reference"],
            "retry_rate": _rate(retried, total),
            "safe_failure_rate": _rate(safe_failures, total),
            "controlled_repair_rate": _rate(repaired, total),
            "average_latency_ms": sum(structured_latencies) / total if total else 0.0,
            "p95_latency_ms": _p95(structured_latencies),
            "validation_error_counts": dict(sorted(errors.items())),
        },
    }


def _load_cases():
    rows = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if len(rows) != 48 or len({row["id"] for row in rows}) != 48:
        raise ValueError("Phase 2C evaluation requires exactly 48 unique cases.")
    return rows


def _baseline_prompt(requirement, clause_text):
    pipeline_input = f"Req: {requirement}\nRule: {clause_text}"
    return (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
        "Analyze this software requirement against the matched framework standard rule.<|eot_id|>"
        f"<|start_header_id|>user<|end_header_id|>\n{pipeline_input}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n"
    )


def _is_json(value):
    try:
        json.loads(value)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def _write_outputs(rows, metrics):
    evaluation = {"metrics": metrics, "cases": rows}
    (DATA_DIR / "evaluation.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    structured = metrics["structured"]
    baseline = metrics["baseline"]
    markdown = f"""# Phase 2C Audit Output Evaluation

- Cases: {metrics['sample_count']}
- Baseline parser success: {baseline['parser_success_rate']:.3f}
- Structured first-attempt valid JSON: {structured['first_attempt_valid_json_rate']:.3f}
- Structured final valid JSON: {structured['final_attempt_valid_json_rate']:.3f}
- Structured schema validation: {structured['schema_validation_rate']:.3f}
- Retry rate: {structured['retry_rate']:.3f}
- Safe-failure rate: {structured['safe_failure_rate']:.3f}
- Controlled-repair rate: {structured['controlled_repair_rate']:.3f}
- Baseline average latency: {baseline['average_latency_ms']:.1f} ms
- Structured average latency: {structured['average_latency_ms']:.1f} ms

Manual 0/1/2 review remains in `manual_review.csv`.
"""
    (DATA_DIR / "evaluation.md").write_text(markdown, encoding="utf-8")

    fields = [
        "id", "category", "requirement", "retrieved_standard", "retrieved_clause",
        "baseline_analysis", "baseline_rewrite", "structured_status", "structured_issue_types",
        "structured_evidence", "structured_explanation", "structured_rewrite",
        "baseline_issue_score", "baseline_grounding_score", "baseline_reference_score",
        "baseline_rewrite_score", "baseline_unsupported_information_score",
        "structured_issue_score", "structured_grounding_score", "structured_reference_score",
        "structured_rewrite_score", "structured_unsupported_information_score", "notes",
    ]
    with (DATA_DIR / "manual_review.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def main():
    import torch
    from app.model_engine import load_pipeline_resources

    parser = argparse.ArgumentParser(description="Evaluate free-form and structured audit output.")
    parser.add_argument(
        "--reuse-baseline",
        action="store_true",
        help="Reuse the previous 48-case baseline when only the structured prompt changed.",
    )
    args = parser.parse_args()
    previous = {}
    if args.reuse_baseline and (DATA_DIR / "evaluation.json").exists():
        existing = json.loads((DATA_DIR / "evaluation.json").read_text(encoding="utf-8"))
        previous = {row["id"]: row for row in existing.get("cases", [])}
        if len(previous) != 48:
            raise ValueError("A complete 48-case baseline is required for reuse.")

    model, tokenizer, vectorstore = load_pipeline_resources()

    def generate_prompt(prompt):
        inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
        outputs = None
        try:
            with torch.no_grad():
                outputs = model.generate(
                    **inputs, max_new_tokens=400, use_cache=True, do_sample=False
                )
            prompt_length = inputs["input_ids"].shape[-1]
            return tokenizer.decode(
                outputs[0][prompt_length:], skip_special_tokens=True
            ).strip()
        finally:
            del inputs
            if outputs is not None:
                del outputs
            torch.cuda.empty_cache()
            gc.collect()

    def generate_messages(messages):
        return "{" + generate_prompt(
            tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            ) + "{"
        )

    rows = []
    for index, case in enumerate(_load_cases(), start=1):
        retrieval = retrieve_standard_evidence(vectorstore, case["requirement"], k=5)
        candidate = retrieval["selected_clause"]

        if (case["id"] in previous
                and previous[case["id"]].get("requirement") == case["requirement"]):
            baseline_raw = previous[case["id"]]["baseline_raw"]
            baseline_latency = previous[case["id"]]["baseline_latency_ms"]
            baseline = parse_stored_audit(baseline_raw)
        else:
            started = time.perf_counter()
            baseline_raw = generate_prompt(
                _baseline_prompt(case["requirement"], candidate["text"] if candidate else "")
            )
            baseline_latency = (time.perf_counter() - started) * 1000
            baseline = parse_stored_audit(baseline_raw)

        started = time.perf_counter()
        structured_run = run_structured_audit(
            case["requirement"], candidate, generate_messages
        )
        structured_latency = (time.perf_counter() - started) * 1000
        audit = structured_run.result.model_dump(mode="json")
        raw_outputs = structured_run.raw_outputs
        reference = audit["standard_reference"] or {}
        rows.append({
            **case,
            "retrieved_standard": reference.get("standard") or (candidate or {}).get("standard", ""),
            "retrieved_clause": reference.get("clause") or (candidate or {}).get("clause", ""),
            "baseline_raw": baseline_raw,
            "baseline_analysis": baseline["explanation"],
            "baseline_rewrite": baseline["suggested_rewrite"],
            "baseline_parser_success": "### Suggested Rewrite" in baseline_raw,
            "baseline_latency_ms": baseline_latency,
            "structured_raw_outputs": raw_outputs,
            "structured_attempts": structured_run.attempts,
            "structured_errors": structured_run.errors,
            "structured_repair_applied": structured_run.repair_applied,
            "structured_first_json_valid": bool(raw_outputs and _is_json(raw_outputs[0])),
            "structured_final_json_valid": bool(raw_outputs and _is_json(raw_outputs[-1])),
            "structured_validation_status": audit["validation_status"],
            "structured_status": audit["compliance_status"],
            "structured_issue_types": ", ".join(audit["issue_types"]),
            "structured_evidence": audit["evidence"],
            "structured_explanation": audit["explanation"],
            "structured_rewrite": audit["suggested_rewrite"],
            "structured_latency_ms": structured_latency,
        })
        print(f"Evaluated {index}/48: {case['id']}")

    metrics = summarize_evaluation(rows)
    _write_outputs(rows, metrics)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
