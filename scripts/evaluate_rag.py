import argparse
import json
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.retrieval import (  # noqa: E402
    ACTIVE_DB_DIR,
    CANDIDATE_DB_DIR,
    create_bge_embeddings,
    open_vectorstore,
)


FIELDS = {"id", "requirement", "expected_standard", "expected_clause", "category"}
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)


def load_examples(path):
    examples = []
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            record = json.loads(line)
            if set(record) != FIELDS:
                raise ValueError(f"Line {line_number} does not use the five-field schema.")
            if bool(record["expected_standard"]) != bool(record["expected_clause"]):
                raise ValueError(f"Line {line_number} has an incomplete expected match.")
            examples.append(record)
    return examples


def _normal(value):
    return " ".join(str(value or "").casefold().split())


def candidate_matches(candidate, example):
    expected_standard = _normal(example["expected_standard"])
    if expected_standard not in _normal(candidate.get("standard")):
        return False
    expected_clause = _normal(example["expected_clause"])
    actual = " ".join([
        _normal(candidate.get("clause")),
        _normal(candidate.get("title")),
        _normal(candidate.get("text")),
    ])
    return expected_clause in actual


def calculate_metrics(examples, rankings, threshold):
    positive = [item for item in examples if item["expected_standard"]]
    negative = [item for item in examples if not item["expected_standard"]]
    hits = {1: 0, 3: 0, 5: 0}
    reciprocal_ranks = []
    errors = []

    for example, candidates in zip(examples, rankings):
        filtered = [item for item in candidates if item["score"] >= threshold]
        if example["expected_standard"]:
            rank = next((index for index, candidate in enumerate(filtered, start=1)
                         if candidate_matches(candidate, example)), None)
            for k in hits:
                hits[k] += bool(rank and rank <= k)
            reciprocal_ranks.append(1 / rank if rank else 0)
            if not rank:
                errors.append({"type": "miss", "example": example,
                               "candidates": filtered})
        elif filtered:
            errors.append({"type": "false_accept", "example": example,
                           "candidates": filtered})

    rejected = sum(
        not [item for item in candidates if item["score"] >= threshold]
        for example, candidates in zip(examples, rankings)
        if not example["expected_standard"]
    )
    return {
        "threshold": threshold,
        "positive_count": len(positive),
        "no_match_count": len(negative),
        "hit_at_1": hits[1] / len(positive) if positive else 0,
        "hit_at_3": hits[3] / len(positive) if positive else 0,
        "hit_at_5": hits[5] / len(positive) if positive else 0,
        "recall_at_5": hits[5] / len(positive) if positive else 0,
        "mrr": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0,
        "no_match_rejection_rate": rejected / len(negative) if negative else 0,
        "errors": errors,
    }


def choose_threshold(examples, rankings):
    results = [calculate_metrics(examples, rankings, value) for value in THRESHOLDS]
    eligible = [result for result in results if result["hit_at_5"] >= 0.9]
    if not eligible:
        return None, results
    selected = max(
        eligible,
        key=lambda result: (
            result["no_match_rejection_rate"],
            result["hit_at_1"],
            result["mrr"],
            -result["threshold"],
        ),
    )
    return selected, results


def retrieve_rankings(store, examples, source_standards=None):
    rankings = []
    durations = []
    store.similarity_search_with_score(examples[0]["requirement"], k=5)
    for _ in range(3):
        started = time.perf_counter()
        current = []
        for example in examples:
            candidates = []
            for document, distance in store.similarity_search_with_score(
                    example["requirement"], k=5):
                metadata = document.metadata or {}
                source = Path(str(metadata.get("source", ""))).name
                candidates.append({
                    "standard": metadata.get("standard", "") or
                                (source_standards or {}).get(source.casefold(), ""),
                    "clause": metadata.get("clause", ""),
                    "title": metadata.get("title", ""),
                    "source": source,
                    "text": document.page_content,
                    "distance": float(distance),
                    "score": 1.0 - float(distance),
                })
            current.append(candidates)
        durations.append((time.perf_counter() - started) * 1000 / len(examples))
        rankings = current
    return rankings, statistics.fmean(durations)


def main():
    parser = argparse.ArgumentParser(description="Evaluate the Phase 2B candidate index.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--method", choices=("candidate", "baseline"), default="candidate")
    parser.add_argument("--candidate-db", type=Path, default=CANDIDATE_DB_DIR)
    parser.add_argument("--baseline-db", type=Path, default=ACTIVE_DB_DIR)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--no-threshold", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "outputs" / "rag_evaluation")
    args = parser.parse_args()

    examples = load_examples(args.dataset)
    source_data = json.loads(
        (PROJECT_ROOT / "data" / "knowledge_base" / "sources.json").read_text(encoding="utf-8")
    )
    source_standards = {
        item["filename"].casefold(): item["standard"] for item in source_data["sources"]
    }
    if args.method == "candidate":
        embeddings = create_bge_embeddings(normalize_embeddings=True)
        store = open_vectorstore(args.candidate_db, embeddings)
    else:
        from langchain_chroma import Chroma

        embeddings = create_bge_embeddings(normalize_embeddings=False)
        store = Chroma(persist_directory=str(args.baseline_db), embedding_function=embeddings)
    rankings, latency = retrieve_rankings(store, examples, source_standards)
    if args.threshold is not None and args.no_threshold:
        parser.error("Use either --threshold or --no-threshold, not both.")
    if args.method == "candidate" and args.threshold is None and not args.no_threshold:
        selected, threshold_results = choose_threshold(examples, rankings)
    else:
        threshold = args.threshold if args.threshold is not None else -999.0
        selected = calculate_metrics(examples, rankings, threshold)
        threshold_results = None
    if selected is not None:
        selected["average_ms_per_requirement"] = latency

    args.output.mkdir(parents=True, exist_ok=True)
    result = {"method": args.method, "dataset": str(args.dataset), "selected": selected,
              "average_ms_per_requirement": latency,
              "activation_ready": selected is not None if args.method == "candidate" else None,
              "threshold_results": threshold_results}
    (args.output / f"{args.method}_evaluation.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    diagnostic = selected or max(
        threshold_results,
        key=lambda item: (item["hit_at_5"], item["no_match_rejection_rate"]),
    )
    (args.output / f"{args.method}_errors.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in diagnostic["errors"]),
        encoding="utf-8",
    )
    summary = [f"# RAG Evaluation: {args.method}", ""]
    if selected is None:
        summary.append("No threshold reached 90% validation Hit@5.")
    else:
        summary.extend(
            f"- {key}: {value}" for key, value in selected.items() if key != "errors"
        )
    (args.output / f"{args.method}_evaluation.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    printable = None if selected is None else {
        key: value for key, value in selected.items() if key != "errors"
    }
    print(json.dumps({"selected": printable, "threshold_results": threshold_results}, indent=2))


if __name__ == "__main__":
    main()
