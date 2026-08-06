import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.requirement_detector import has_modal_keyword
from scripts.prepare_requirement_detection_data import (
    CATEGORY_LABELS, validate_generation_batch, validate_sample, write_jsonl,
)


DEFAULT_MODEL = "gemini-2.5-flash"
CATEGORY = Literal[
    "functional_modal", "functional_no_modal", "nonfunctional_modal",
    "nonfunctional_no_modal", "poorly_written_requirement", "background",
    "purpose", "definition", "implementation_note", "hard_negative_modal",
]


class GeneratedRow(BaseModel):
    text: str
    category: CATEGORY


class GeneratedBatch(BaseModel):
    rows: list[GeneratedRow]


PROMPT = """
Generate exactly 50 short English SRS-style text samples for a binary
Requirement versus Non-requirement classifier. Return exactly five samples for
each category below. Do not audit quality or mention standards.

Requirement categories:
- functional_modal: functional software requirements with shall/must/should/will/needs to/required to
- functional_no_modal: functional software requirements without those modal phrases
- nonfunctional_modal: measurable quality requirements with modal phrases
- nonfunctional_no_modal: measurable quality requirements without modal phrases
- poorly_written_requirement: genuine but ambiguous, incomplete, or informal software requirements

Non-requirement categories:
- background: context or existing-state descriptions
- purpose: document or project purpose statements
- definition: term definitions and glossary statements
- implementation_note: design decisions or developer guidance, not required system behaviour
- hard_negative_modal: project/process statements containing modal phrases but not software requirements

Every functional_modal, nonfunctional_modal, and hard_negative_modal row must
contain at least one exact phrase from: shall, should, must, needs to, will,
required to. Every functional_no_modal and nonfunctional_no_modal row must avoid
all six phrases.

Use diverse web, enterprise, IoT, smart-manufacturing, mobile, security, and
reporting scenarios. Include both well-written and realistic imperfect text.
Each row must contain only `text` and `category`. Avoid duplicates and
paraphrases within the batch. {split_instruction}
Batch identifier: {batch_id}
"""


def canonicalize_rows(rows, batch_id):
    canonical = []
    for raw in rows:
        row = raw.model_dump() if isinstance(raw, GeneratedRow) else raw
        if set(row) != {"text", "category"}:
            raise ValueError("Generated rows must contain only text and category.")
        category = row["category"]
        if category not in CATEGORY_LABELS:
            raise ValueError(f"Unknown category: {category}")
        canonical.append(validate_sample({
            "text": row["text"].strip(),
            "label": CATEGORY_LABELS[category],
            "category": category,
            "has_modal": has_modal_keyword(row["text"]),
            "source": "synthetic",
            "generation_batch": batch_id,
        }))
    validate_generation_batch(canonical)
    return canonical


def existing_batch_is_valid(path, batch_id):
    try:
        rows = []
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = validate_sample(json.loads(line))
                    if row["generation_batch"] != batch_id:
                        return False
                    rows.append(row)
        validate_generation_batch(rows)
        return True
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def create_gemini_client(api_key):
    from google import genai
    from google.genai import types
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def generate_batch(client, model, mode, batch_id):
    from google.genai import types

    split_instruction = (
        "This is an independent final-test candidate batch. Use fresh scenarios "
        "and wording that are not template-like."
        if mode == "test" else
        "This is development data for training or validation."
    )
    prompt = PROMPT.format(
        split_instruction=split_instruction, batch_id=batch_id
    )
    last_error = None
    for _ in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.8,
                    response_mime_type="application/json",
                    response_schema=GeneratedBatch,
                ),
            )
            parsed = response.parsed
            if not isinstance(parsed, GeneratedBatch):
                parsed = GeneratedBatch.model_validate_json(response.text)
            return canonicalize_rows(parsed.rows, batch_id)
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Gemini failed to generate {batch_id}: {last_error}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic requirement detection batches with Gemini."
    )
    parser.add_argument("--mode", choices=("dev", "test"), required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--batches", type=int, default=2)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--output-root",
        default=PROJECT_ROOT / "outputs" / "requirement_detection" / "generated",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY or GOOGLE_API_KEY is required.")

    client = create_gemini_client(api_key)
    output_dir = Path(args.output_root) / args.mode
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        for index in range(args.start, args.start + args.batches):
            batch_id = f"{args.mode}_batch_{index:03d}"
            output_path = output_dir / f"{batch_id}.jsonl"
            if output_path.exists() and existing_batch_is_valid(output_path, batch_id):
                print(f"Skipping existing batch: {batch_id}")
                continue
            if output_path.exists():
                print(f"Regenerating invalid batch: {batch_id}")
            samples = generate_batch(client, args.model, args.mode, batch_id)
            write_jsonl(samples, output_path)
            print(f"Wrote {len(samples)} samples: {output_path}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
