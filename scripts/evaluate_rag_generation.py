import argparse
import csv
import json
import math
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "audit_evaluation"
EVALUATION_PATH = DATA_DIR / "evaluation.json"
V1_JUDGE_PATH = DATA_DIR / "generation_quality_judge.jsonl"
JUDGE_PATH = DATA_DIR / "generation_quality_judge_v2.jsonl"
EXPERT_PATH = DATA_DIR / "generation_quality_expert_review_v2.csv"
SUMMARY_JSON_PATH = DATA_DIR / "generation_quality_summary_v2.json"
SUMMARY_MD_PATH = DATA_DIR / "generation_quality_summary_v2.md"
RETRIEVAL_PATH = PROJECT_ROOT / "outputs" / "rag_evaluation" / "candidate_evaluation.json"
DEFAULT_MODELS = ("gemini-2.5-flash", "gemini-3.1-pro-preview")
PROMPT_VERSION = "rag-generation-quality-v2.1"
SAMPLE_SEED = 20260820
SCORE_VALUES = (0, 1, 2)
EXPERT_CASE_IDS = (
    "rag_val_003", "rag_val_008", "rag_val_010", "rag_val_012", "rag_val_014",
    "rag_val_016", "rag_val_022", "rag_val_027", "rag_val_035", "rag_val_037",
)
EVIDENCE_OVERRIDES = {
    "rag_val_008": (
        "9.6.14 Performance requirements\n"
        "Specify both the static and the dynamic numerical requirements placed on the software "
        "or on human interaction with the software as a whole. Static numerical requirements "
        "may include the number of terminals, the number of simultaneous users, and the amount "
        "and type of information to be handled. Dynamic numerical requirements may include the "
        "numbers of transactions and tasks and the amount of data to be processed within "
        "specified time periods for normal and peak workload conditions. The performance "
        "requirements should be stated in measurable terms."
    ),
}
HUMAN_FIELDS = (
    "expert_faithfulness_score",
    "expert_answer_relevance_score",
    "expert_comments",
    "researcher_adjudicated_faithfulness_score",
    "researcher_adjudicated_answer_relevance_score",
    "researcher_notes",
)


class JudgeScores(BaseModel):
    faithfulness_score: int = Field(ge=0, le=2)
    answer_relevance_score: int = Field(ge=0, le=2)
    faithfulness_reason: str = Field(min_length=1, max_length=600)
    answer_relevance_reason: str = Field(min_length=1, max_length=600)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=10)


JUDGE_PROMPT = """You are independently evaluating exactly the four fields shown to a human
software-requirements expert. Use only those fields. Do not use outside knowledge and do not
infer any hidden compliance status or issue labels.

FAITHFULNESS
Score only the Explanation.
2 = every meaningful claim in the explanation is supported by the Requirement or Evidence.
1 = the main explanation is supported, but a minor claim or assumption is unsupported.
0 = the explanation contradicts the inputs or invents a standard, actor, threshold, condition,
    or behaviour.

ANSWER RELEVANCE
Score only the Suggested Rewrite against the Requirement and the issue described in the
Explanation.
2 = the rewrite directly addresses the issue while preserving the original intent.
1 = the rewrite partly addresses the issue, misses an important part, or adds unnecessary text.
0 = the rewrite is unrelated, contradictory, or fails to address the issue.
If the explanation identifies no drafting issue, or only says the Evidence is irrelevant or
insufficient, leaving the Requirement unchanged may score 2. Do not expect the rewrite to repair
a retrieval problem.

Return only the requested JSON fields. Keep reasons concise. List each unsupported claim
from the Explanation verbatim when possible; otherwise return an empty list.

CASE
{case_json}
"""


def normalize_score(value: int) -> float:
    if type(value) is not int or value not in SCORE_VALUES:
        raise ValueError("Scores must be integers from 0 to 2.")
    return value / 2


def _normal(value) -> str:
    return " ".join(str(value or "").casefold().split())


def format_evidence(case_id: str, standard: str, clause: str, context: str) -> str:
    clause = clause or "Not specified"
    context = EVIDENCE_OVERRIDES.get(case_id, context)
    return f"{standard} - Clause {clause}\n{context}"


def judge_input(case: dict) -> dict:
    return {
        key: case[key] for key in (
            "requirement", "evidence", "explanation", "suggested_rewrite"
        )
    }


def load_evaluation(path: Path = EVALUATION_PATH):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    required = {
        "id", "category", "requirement", "expected_standard", "retrieved_standard",
        "retrieved_clause", "structured_status", "structured_issue_types",
        "structured_evidence", "structured_explanation", "structured_rewrite",
    }
    if len(cases) != 48 or len({row.get("id") for row in cases}) != 48:
        raise ValueError("Generation-quality evaluation requires 48 unique cases.")
    for row in cases:
        missing = required - set(row)
        if missing:
            raise ValueError(f"{row.get('id', 'Unknown case')} is missing: {sorted(missing)}")
    return cases, payload.get("metrics", {})


def prepare_case(row: dict, candidate: dict) -> dict:
    if not candidate:
        raise ValueError(f"{row['id']}: retrieval returned no Top-1 evidence.")
    stored = (_normal(row["retrieved_standard"]), _normal(row["retrieved_clause"]))
    current = (_normal(candidate.get("standard")), _normal(candidate.get("clause")))
    if stored != current:
        raise ValueError(
            f"{row['id']}: saved retrieval metadata {stored} no longer matches {current}; "
            "rerun scripts/evaluate_audit_output.py --reuse-baseline before judging."
        )
    return {
        "id": row["id"],
        "category": row["category"],
        "expected_match": bool(row["expected_standard"]),
        "requirement": row["requirement"],
        "retrieved_standard": candidate.get("standard", ""),
        "retrieved_clause": candidate.get("clause", ""),
        "retrieved_source": candidate.get("source", ""),
        "retrieval_score": candidate.get("score"),
        "retrieved_context": candidate.get("text", ""),
        "evidence": format_evidence(
            row["id"], candidate.get("standard", ""), candidate.get("clause", ""),
            candidate.get("text", ""),
        ),
        "explanation": row["structured_explanation"],
        "suggested_rewrite": row["structured_rewrite"],
    }


def retrieve_contexts(cases: list[dict]) -> list[dict]:
    from app.retrieval import open_runtime_vectorstore, retrieve_standard_evidence

    store = open_runtime_vectorstore()
    prepared = []
    for index, row in enumerate(cases, start=1):
        result = retrieve_standard_evidence(store, row["requirement"], k=5)
        prepared.append(prepare_case(row, result["selected_clause"]))
        print(f"Verified retrieval {index}/48: {row['id']}")
    return prepared


def select_expert_ids(cases: list[dict], count: int = 15,
                      seed: int = SAMPLE_SEED) -> list[str]:
    groups = defaultdict(list)
    for row in cases:
        groups[row["category"]].append(row)
    if count < len(groups) or count > len(cases):
        raise ValueError("Expert sample size must cover every category.")
    rng = random.Random(seed)
    selected = [
        rng.choice(sorted(groups[category], key=lambda row: row["id"]))
        for category in sorted(groups)
    ]
    selected_ids = {row["id"] for row in selected}
    remaining = sorted(
        (row for row in cases if row["id"] not in selected_ids),
        key=lambda row: row["id"],
    )
    selected.extend(rng.sample(remaining, count - len(selected)))
    return sorted(row["id"] for row in selected)


def _expert_row(case: dict) -> dict:
    row = {
        key: case[key] for key in (
            "id", "category", "requirement", "evidence", "explanation",
            "suggested_rewrite",
        )
    }
    row.update({field: "" for field in HUMAN_FIELDS})
    return row


def write_expert_review(cases: list[dict], path: Path = EXPERT_PATH,
                        selected_ids: tuple[str, ...] = EXPERT_CASE_IDS) -> None:
    by_id = {row["id"]: row for row in cases}
    missing = set(selected_ids) - set(by_id)
    if missing:
        raise ValueError(f"Expert cases are missing: {sorted(missing)}")
    rows = [_expert_row(by_id[case_id]) for case_id in selected_ids]
    existing = {}
    if Path(path).exists():
        with Path(path).open(encoding="utf-8-sig", newline="") as source:
            existing = {row["id"]: row for row in csv.DictReader(source)}
    core_fields = [field for field in rows[0] if field not in HUMAN_FIELDS]
    for row in rows:
        previous = existing.get(row["id"])
        if not previous:
            continue
        scored = any(previous.get(field, "").strip() for field in HUMAN_FIELDS)
        if scored and any(previous.get(field, "") != str(row[field]) for field in core_fields):
            raise ValueError(f"{row['id']}: evaluation input changed after expert scoring.")
        for field in HUMAN_FIELDS:
            row[field] = previous.get(field, "")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def judge_case(client, model: str, case: dict) -> JudgeScores:
    from google.genai import types

    case_json = json.dumps(judge_input(case), ensure_ascii=False, indent=2)
    last_error = None
    for _ in range(2):
        try:
            response = client.models.generate_content(
                model=model,
                contents=JUDGE_PROMPT.format(case_json=case_json),
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=JudgeScores,
                ),
            )
            parsed = response.parsed
            return parsed if isinstance(parsed, JudgeScores) else JudgeScores.model_validate_json(
                response.text
            )
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Judge failed after one retry: {last_error}")


def judge_record(case: dict, result: JudgeScores | None, model: str,
                 error: str = "") -> dict:
    record = {
        **case,
        "judge_model": model,
        "prompt_version": PROMPT_VERSION,
        "faithfulness_score": None,
        "faithfulness_normalized": None,
        "answer_relevance_score": None,
        "answer_relevance_normalized": None,
        "faithfulness_reason": "",
        "answer_relevance_reason": "",
        "unsupported_claims": [],
        "error": error,
    }
    if result is not None:
        record.update({
            **result.model_dump(),
            "faithfulness_normalized": normalize_score(result.faithfulness_score),
            "answer_relevance_normalized": normalize_score(result.answer_relevance_score),
        })
    return record


def write_jsonl(rows: list[dict], path: Path) -> None:
    Path(path).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_saved_cases(path: Path = V1_JUDGE_PATH) -> list[dict]:
    rows = read_jsonl(path)
    if len(rows) != 48 or len({row.get("id") for row in rows}) != 48:
        raise ValueError("The saved v1 input artifact must contain 48 unique cases.")
    required = {
        "id", "category", "expected_match", "requirement", "retrieved_standard",
        "retrieved_clause", "retrieved_source", "retrieval_score", "retrieved_context",
        "explanation", "suggested_rewrite",
    }
    prepared = []
    for row in rows:
        missing = required - set(row)
        if missing:
            raise ValueError(f"{row.get('id', 'Unknown case')} is missing: {sorted(missing)}")
        prepared.append({
            key: row[key] for key in (
                "id", "category", "expected_match", "requirement", "retrieved_standard",
                "retrieved_clause", "retrieved_source", "retrieval_score",
                "retrieved_context", "explanation", "suggested_rewrite",
            )
        })
        prepared[-1]["evidence"] = format_evidence(
            row["id"], row["retrieved_standard"], row["retrieved_clause"],
            row["retrieved_context"],
        )
    return prepared


def _metric_summary(rows: list[dict], field: str) -> dict:
    scores = [row[field] for row in rows if not row.get("error") and row[field] is not None]
    counts = Counter(scores)
    return {
        "scored_count": len(scores),
        "mean_normalized": statistics.fmean(scores) / 2 if scores else None,
        "median_normalized": statistics.median(scores) / 2 if scores else None,
        "score_counts": {str(score): counts[score] for score in SCORE_VALUES},
    }


def summarize_judgements(rows: list[dict]) -> dict:
    return {"all": {
        "case_count": len(rows),
        "error_count": sum(bool(row.get("error")) for row in rows),
        "faithfulness": _metric_summary(rows, "faithfulness_score"),
        "answer_relevance": _metric_summary(rows, "answer_relevance_score"),
    }}


def representative_failures(rows: list[dict], limit: int = 3) -> dict:
    valid = [row for row in rows if not row.get("error")]
    faithfulness = sorted(
        (row for row in valid if row["faithfulness_score"] == 0),
        key=lambda row: row["id"],
    )[:limit]
    relevance = sorted(
        (row for row in valid if row["answer_relevance_score"] == 0),
        key=lambda row: row["id"],
    )[:limit]
    return {
        "faithfulness": [{
            "id": row["id"],
            "reason": row["faithfulness_reason"],
            "unsupported_claims": row["unsupported_claims"],
        } for row in faithfulness],
        "answer_relevance": [{
            "id": row["id"],
            "reason": row["answer_relevance_reason"],
        } for row in relevance],
    }


def score_agreement(expert: list[int], judge: list[int]) -> dict:
    if len(expert) != len(judge) or not expert:
        raise ValueError("Agreement requires two non-empty, equal-length score lists.")
    from sklearn.metrics import cohen_kappa_score

    kappa = float(cohen_kappa_score(expert, judge, weights="quadratic"))
    return {
        "count": len(expert),
        "exact_agreement": sum(a == b for a, b in zip(expert, judge)) / len(expert),
        "quadratic_weighted_kappa": None if math.isnan(kappa) else kappa,
    }


def _optional_score(value: str):
    if not str(value or "").strip():
        return None
    score = int(value)
    normalize_score(score)
    return score


def summarize_judges(judge_rows: list[dict]) -> dict:
    models = sorted({row["judge_model"] for row in judge_rows})
    by_model = {
        model: summarize_judgements([
            row for row in judge_rows if row["judge_model"] == model
        ])
        for model in models
    }
    agreement = {}
    for first, second in combinations(models, 2):
        first_rows = {
            row["id"]: row for row in judge_rows
            if row["judge_model"] == first and not row.get("error")
        }
        second_rows = {
            row["id"]: row for row in judge_rows
            if row["judge_model"] == second and not row.get("error")
        }
        ids = sorted(set(first_rows) & set(second_rows))
        pair = {"case_count": len(ids), "faithfulness": None, "answer_relevance": None}
        if ids:
            for metric in ("faithfulness", "answer_relevance"):
                field = f"{metric}_score"
                pair[metric] = score_agreement(
                    [first_rows[case_id][field] for case_id in ids],
                    [second_rows[case_id][field] for case_id in ids],
                )
        agreement[f"{first} vs {second}"] = pair
    return {"by_model": by_model, "judge_agreement": agreement}


def summarize_expert(path: Path, judge_rows: list[dict]) -> dict:
    if not Path(path).exists():
        return {"case_count": 0, "complete": False}
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        expert_rows = list(csv.DictReader(source))
    if len(expert_rows) != len(EXPERT_CASE_IDS):
        raise ValueError(f"Expert review must contain exactly {len(EXPERT_CASE_IDS)} cases.")
    models = sorted({row["judge_model"] for row in judge_rows})
    by_model = {}
    complete = all(
        _optional_score(row.get(field, "")) is not None
        for row in expert_rows
        for field in ("expert_faithfulness_score", "expert_answer_relevance_score")
    )
    for model in models:
        judge_by_id = {
            row["id"]: row for row in judge_rows
            if row["judge_model"] == model and not row.get("error")
        }
        pairs = {"faithfulness": ([], []), "answer_relevance": ([], [])}
        for row in expert_rows:
            judge = judge_by_id.get(row["id"], {})
            for name, expert_field, judge_field in (
                ("faithfulness", "expert_faithfulness_score", "faithfulness_score"),
                ("answer_relevance", "expert_answer_relevance_score", "answer_relevance_score"),
            ):
                expert_score = _optional_score(row.get(expert_field, ""))
                judge_score = judge.get(judge_field)
                if expert_score is not None and judge_score is not None:
                    pairs[name][0].append(expert_score)
                    pairs[name][1].append(judge_score)
        model_complete = complete and all(
            len(expert) == len(EXPERT_CASE_IDS) for expert, _ in pairs.values()
        )
        by_model[model] = {
            "complete": model_complete,
            "faithfulness": score_agreement(*pairs["faithfulness"]) if model_complete else None,
            "answer_relevance": (
                score_agreement(*pairs["answer_relevance"]) if model_complete else None
            ),
        }
    return {
        "case_count": len(EXPERT_CASE_IDS),
        "complete": complete,
        "by_model": by_model,
    }


def _retrieval_summary(path: Path) -> dict:
    if not Path(path).exists():
        return {"available": False}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    diagnostic = payload.get("selected")
    if diagnostic is None and payload.get("threshold_results"):
        diagnostic = max(
            payload["threshold_results"],
            key=lambda row: (row["hit_at_5"], row["no_match_rejection_rate"]),
        )
    return {
        "available": diagnostic is not None,
        "activation_ready": payload.get("activation_ready"),
        "average_ms_per_requirement": payload.get("average_ms_per_requirement"),
        "diagnostic": {
            key: diagnostic.get(key) for key in (
                "threshold", "hit_at_1", "hit_at_5", "mrr"
            )
        } if diagnostic else None,
    }


def build_summary(judge_rows: list[dict], structural: dict,
                  expert_path: Path = EXPERT_PATH,
                  retrieval_path: Path = RETRIEVAL_PATH) -> dict:
    semantic = summarize_judges(judge_rows)
    return {
        "structural_reliability": structural.get("structured", {}),
        "retrieval_quality": _retrieval_summary(retrieval_path),
        "semantic_generation_quality": semantic,
        "representative_failures": {
            model: representative_failures([
                row for row in judge_rows if row["judge_model"] == model
            ])
            for model in semantic["by_model"]
        },
        "expert_validation": summarize_expert(expert_path, judge_rows),
        "interpretation": (
            "Descriptive only. Version 2 scores only the explanation and suggested rewrite "
            "shown to the Expert. The free-form baseline also received retrieved evidence, so "
            "these results do not establish improvement over a non-RAG model."
        ),
    }


def write_summary(summary: dict) -> None:
    SUMMARY_JSON_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    structural = summary["structural_reliability"]
    retrieval = summary["retrieval_quality"]
    semantic = summary["semantic_generation_quality"]
    lines = [
        "# RAG Generation-Quality Evaluation", "",
        "Results are descriptive. Structural, retrieval, and semantic measures are separate.", "",
        "## Structural reliability", "",
        "| Measure | Value |", "| --- | ---: |",
        f"| Schema validation | {structural.get('schema_validation_rate', 0):.3f} |",
        f"| Safe failure | {structural.get('safe_failure_rate', 0):.3f} |",
        f"| Retry | {structural.get('retry_rate', 0):.3f} |",
        f"| Controlled repair | {structural.get('controlled_repair_rate', 0):.3f} |", "",
        "## Retrieval quality", "",
    ]
    if retrieval.get("available"):
        item = retrieval["diagnostic"]
        lines.extend([
            "| Measure | Value |", "| --- | ---: |",
            f"| Diagnostic threshold | {item['threshold']:.3f} |",
            f"| Hit@1 | {item['hit_at_1']:.3f} |",
            f"| Hit@5 | {item['hit_at_5']:.3f} |",
            f"| MRR | {item['mrr']:.3f} |", "",
        ])
    else:
        lines.extend(["No retrieval evaluation artifact was available.", ""])
    lines.extend(["## Semantic generation quality", ""])
    for model, model_summary in semantic["by_model"].items():
        lines.extend([f"### Judge: {model}", ""])
        for group_name in ("all",):
            group = model_summary[group_name]
            lines.extend([
                f"#### {group_name.replace('_', ' ').title()} (n={group['case_count']})", "",
                "| Metric | Scored | Mean (0-1) | Median (0-1) | Score 0 | Score 1 | Score 2 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ])
            for label, key in (("Faithfulness", "faithfulness"),
                               ("Answer relevance", "answer_relevance")):
                metric = group[key]
                mean = "PENDING" if metric["mean_normalized"] is None else f"{metric['mean_normalized']:.3f}"
                median = "PENDING" if metric["median_normalized"] is None else f"{metric['median_normalized']:.3f}"
                counts = metric["score_counts"]
                lines.append(
                    f"| {label} | {metric['scored_count']} | {mean} | {median} | "
                    f"{counts['0']} | {counts['1']} | {counts['2']} |"
                )
            if group["error_count"]:
                lines.append(
                    f"\nJudge errors: {group['error_count']}; do not treat this section as complete."
                )
            lines.append("")
    lines.extend(["## Inter-judge agreement", ""])
    for pair_name, pair in semantic["judge_agreement"].items():
        lines.extend([
            f"### {pair_name} (n={pair['case_count']})", "",
            "| Metric | Exact agreement | Quadratic weighted kappa |",
            "| --- | ---: | ---: |",
        ])
        for label, key in (("Faithfulness", "faithfulness"),
                           ("Answer relevance", "answer_relevance")):
            metric = pair[key]
            if metric is None:
                lines.append(f"| {label} | PENDING | PENDING |")
                continue
            kappa = metric["quadratic_weighted_kappa"]
            lines.append(
                f"| {label} | {metric['exact_agreement']:.3f} | "
                f"{'N/A' if kappa is None else f'{kappa:.3f}'} |"
            )
        lines.append("")
    expert = summary["expert_validation"]
    lines.extend(["## Expert validation", ""])
    if expert.get("complete"):
        for model, result in expert["by_model"].items():
            if not result["complete"]:
                continue
            lines.extend([
                f"### Expert vs {model}", "",
                "| Metric | Exact agreement | Quadratic weighted kappa |",
                "| --- | ---: | ---: |",
            ])
            for label, key in (("Faithfulness", "faithfulness"),
                               ("Answer relevance", "answer_relevance")):
                metric = result[key]
                kappa = metric["quadratic_weighted_kappa"]
                lines.append(
                    f"| {label} | {metric['exact_agreement']:.3f} | "
                    f"{'N/A' if kappa is None else f'{kappa:.3f}'} |"
                )
            lines.append("")
    else:
        lines.extend([
            f"PENDING: the blinded {expert.get('case_count', 10)}-case Expert sheet has not been fully scored.", "",
        ])
    lines.extend(["## Representative judge-flagged failures", ""])
    for model, failures in summary["representative_failures"].items():
        lines.extend([f"### Judge: {model}", ""])
        for label, key in (("Faithfulness", "faithfulness"),
                           ("Answer relevance", "answer_relevance")):
            lines.extend([f"#### {label}", "", "| Case | Reason |", "| --- | --- |"])
            for item in failures[key]:
                reason = item["reason"].replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {item['id']} | {reason} |")
            lines.append("")
    lines.extend([
        "## Interpretation boundary", "",
        summary["interpretation"], "",
    ])
    SUMMARY_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate Expert-visible explanation faithfulness and rewrite relevance."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--refresh-inputs", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if len(set(args.models)) != len(args.models):
        raise SystemExit("Judge model names must be unique.")

    cases, structural = load_evaluation()
    if args.summarize_only:
        rows = read_jsonl(JUDGE_PATH)
        write_summary(build_summary(rows, structural))
        print(f"Wrote {SUMMARY_JSON_PATH} and {SUMMARY_MD_PATH}.")
        return

    prepared = retrieve_contexts(cases) if args.refresh_inputs else load_saved_cases()
    write_expert_review(prepared)
    print(f"Wrote blinded {len(EXPERT_CASE_IDS)}-case review sheet: {EXPERT_PATH}")
    if args.prepare_only:
        return

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY or GOOGLE_API_KEY is required for judging.")
    from scripts.generate_requirement_detection_data import create_gemini_client

    client = create_gemini_client(api_key)
    rows = [] if args.force or not JUDGE_PATH.exists() else [
        row for row in read_jsonl(JUDGE_PATH)
        if row.get("prompt_version") == PROMPT_VERSION
        and row.get("judge_model") in args.models
    ]
    by_key = {(row["judge_model"], row["id"]): row for row in rows}
    try:
        for model in args.models:
            for index, case in enumerate(prepared, start=1):
                key = (model, case["id"])
                if key in by_key and not by_key[key].get("error"):
                    print(f"Reused {model} {index}/48: {case['id']}")
                    continue
                try:
                    result = judge_case(client, model, case)
                    by_key[key] = judge_record(case, result, model)
                except Exception as error:
                    by_key[key] = judge_record(case, None, model, str(error))
                rows = sorted(
                    by_key.values(),
                    key=lambda row: (args.models.index(row["judge_model"]), row["id"]),
                )
                write_jsonl(rows, JUDGE_PATH)
                print(f"Judged {model} {index}/48: {case['id']}")
    finally:
        client.close()
    rows = sorted(
        by_key.values(),
        key=lambda row: (args.models.index(row["judge_model"]), row["id"]),
    )
    write_jsonl(rows, JUDGE_PATH)
    summary = build_summary(rows, structural)
    write_summary(summary)
    errors = sum(
        model_summary["all"]["error_count"]
        for model_summary in summary["semantic_generation_quality"]["by_model"].values()
    )
    expected = 48 * len(args.models)
    if len(rows) != expected or len(by_key) != expected or errors:
        raise SystemExit(f"Judge evaluation is incomplete: {len(rows)} rows, {errors} errors.")
    print(f"Wrote complete judge results: {JUDGE_PATH}")


if __name__ == "__main__":
    main()
