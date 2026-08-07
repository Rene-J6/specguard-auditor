import argparse
import csv
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "rag_evaluation"
VALIDATION_PATH = DATA_DIR / "validation.jsonl"
REVIEW_PATH = DATA_DIR / "test_review.csv"
TEST_PATH = DATA_DIR / "test.jsonl"
TEST_MANIFEST_PATH = DATA_DIR / "test_manifest.json"

ISO_29148 = "ISO/IEC/IEEE 29148:2018"


CASES = {
    "functional_suitability": (ISO_29148, "9.5.5", [
        "The system shall calculate the final invoice total including all applicable taxes.",
        "The portal shall allow customers to download each completed invoice.",
        "The application shall verify that every mandatory registration field is supplied.",
        "The system shall display the correct account balance after a confirmed payment.",
        "Users shall be able to search orders by order number and customer name.",
        "The system shall generate a receipt after a payment is successfully processed.",
        "The application shall reject a booking when the selected slot is unavailable.",
        "The portal shall show every open support ticket assigned to the signed-in user.",
        "The service shall calculate delivery charges from the destination and parcel weight.",
        "The system shall export the selected audit findings as a DOCX report.",
    ]),
    "performance_efficiency": (ISO_29148, "9.5.7", [
        "The dashboard shall load within two seconds for 95 percent of requests.",
        "The API shall process at least 100 transactions per second.",
        "A search response shall be returned within 500 milliseconds under normal load.",
        "The service shall support 500 concurrent authenticated users.",
        "The application shall use no more than 1 GB of memory during normal operation.",
        "The report shall be generated within five seconds for 10,000 audit findings.",
        "The system shall sustain 50 file uploads per minute without request loss.",
        "Database queries shall complete within one second for 95 percent of requests.",
        "The client shall remain responsive while a 100 MB document is uploaded.",
        "The nightly import shall process one million records within thirty minutes.",
    ]),
    "security": (ISO_29148, "9.5.13", [
        "The system shall lock an account after five consecutive failed login attempts.",
        "Stored passwords shall be protected using a one-way password hash.",
        "Only administrators shall be permitted to create Expert accounts.",
        "The system shall record the identity and time of every administrative change.",
        "Session cookies shall not be accessible to client-side scripts.",
        "The application shall prevent a User from invoking Expert review operations.",
        "Confidential customer records shall be encrypted while stored.",
        "The server shall invalidate all sessions when an account is disabled.",
        "Every downloaded audit report shall be restricted to its document owner.",
        "The system shall verify the integrity of imported configuration files.",
    ]),
    "usability": (ISO_29148, "9.5.6", [
        "The interface shall explain how a user can correct every validation error.",
        "A first-time user shall complete document upload without external training.",
        "The application shall provide keyboard access to every primary action.",
        "Form labels shall remain visible while the user enters information.",
        "The system shall ask for confirmation before deleting an audit document.",
        "Error messages shall identify the affected field and the corrective action.",
        "The upload screen shall show the accepted file types before file selection.",
        "The interface shall preserve entered values after a validation failure.",
        "Users shall reach their document history within two navigation actions.",
        "Text and controls shall remain readable at 200 percent browser zoom.",
    ]),
    "reliability": (ISO_29148, "9.5.9.3", [
        "The service shall achieve 99.9 percent monthly availability.",
        "The system shall restore normal processing within five minutes of a worker failure.",
        "No confirmed audit record shall be lost after an unexpected restart.",
        "The application shall continue read-only operation when report generation fails.",
        "The database shall recover to a consistent state after a power interruption.",
        "The API shall reject an incomplete transaction without saving partial audit data.",
        "The service shall automatically reconnect after a temporary database interruption.",
        "A failed document analysis shall not prevent later documents from being processed.",
        "The system shall retain committed user data after an application crash.",
        "The application shall detect and report an unavailable model dependency.",
    ]),
    "maintainability": (ISO_29148, "9.5.9.2", [
        "The authentication component shall be testable independently from document analysis.",
        "A change to the retrieval threshold shall not require changes to the LLM module.",
        "The system shall record diagnostic information for each failed ingestion run.",
        "Requirement detection shall remain independent from standards retrieval.",
        "Automated tests shall cover every supported audit lifecycle transition.",
        "The retrieval module shall be replaceable without changing authentication routes.",
        "Each knowledge-base source shall have a deterministic ingestion identifier.",
        "The application shall isolate report generation from audit persistence logic.",
        "Configuration values shall be defined in one documented location.",
        "A developer shall be able to test clause parsing without loading the LLM.",
    ]),
    "compatibility": (ISO_29148, "9.5.8", [
        "The application shall exchange audit results with Microsoft Word using DOCX files.",
        "The service shall coexist with other local applications on the same workstation.",
        "Exported JSON shall use UTF-8 so it can be consumed by external tools.",
        "The API shall accept documents uploaded by current Chrome and Edge browsers.",
        "The system shall import standards produced by the existing document repository.",
        "The application shall exchange timestamps using the ISO 8601 representation.",
        "The service shall run while the local database is accessed by the reporting module.",
        "Generated reports shall open correctly in Microsoft Word and LibreOffice.",
        "The API shall return JSON that conforms to the documented client contract.",
        "The system shall preserve Unicode text exchanged with external document tools.",
    ]),
    "requirement_quality": (ISO_29148, "5.2.5", [
        "Each requirement shall state one capability and use measurable acceptance criteria.",
        "The specification shall identify every requirement with a unique identifier.",
        "A requirement shall be written so that it has only one reasonable interpretation.",
        "Every requirement shall be verifiable by inspection, analysis, demonstration, or test.",
        "Requirements shall avoid unnecessary implementation constraints.",
        "Each requirement shall contain enough information to be understood independently.",
        "A requirement shall describe a necessary capability rather than optional commentary.",
        "The requirement set shall not contain conflicting statements.",
        "Each quality requirement shall include a measurable target and operating condition.",
        "A requirement shall express a single function, quality, or constraint.",
    ]),
}

NO_MATCH = [
    "The project team must complete testing by Friday.",
    "The product owner will present the roadmap at the next meeting.",
    "Developers should update their weekly timesheets.",
    "The company must renew the software contract this month.",
    "The training room will be available after lunch.",
    "The implementation team should consider hiring another engineer.",
    "Management requires the budget proposal before the quarter ends.",
    "The vendor shall attend the project kickoff meeting.",
    "The project manager must submit the progress report every Monday.",
    "Team members will review the sprint retrospective notes tomorrow.",
    "The procurement department shall obtain three supplier quotations.",
    "The client should approve the visual design before development begins.",
    "The support team must complete product training next week.",
    "The steering committee will decide the final launch date.",
    "The analyst is required to arrange stakeholder interviews.",
    "All developers shall follow the office attendance policy.",
]


def build_examples(split):
    start = 0 if split == "validation" else 5
    prefix = "val" if split == "validation" else "test"
    examples = []
    number = 1
    for category, (standard, clause, requirements) in CASES.items():
        for requirement in requirements[start:start + 5]:
            examples.append({
                "id": f"rag_{prefix}_{number:03d}",
                "requirement": requirement,
                "expected_standard": standard,
                "expected_clause": clause,
                "category": category,
            })
            number += 1
    no_match_start = 0 if split == "validation" else 8
    for requirement in NO_MATCH[no_match_start:no_match_start + 8]:
        examples.append({
            "id": f"rag_{prefix}_{number:03d}",
            "requirement": requirement,
            "expected_standard": None,
            "expected_clause": None,
            "category": "no_match",
        })
        number += 1
    return examples


def _write_jsonl(path, records):
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")


def create_review_files():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _write_jsonl(VALIDATION_PATH, build_examples("validation"))
    fields = ["id", "requirement", "proposed_standard", "proposed_clause", "category",
              "decision", "corrected_standard", "corrected_clause", "notes"]
    with REVIEW_PATH.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for item in build_examples("test"):
            writer.writerow({
                "id": item["id"],
                "requirement": item["requirement"],
                "proposed_standard": item["expected_standard"] or "",
                "proposed_clause": item["expected_clause"] or "",
                "category": item["category"],
                "decision": "",
                "corrected_standard": "",
                "corrected_clause": "",
                "notes": "",
            })
    print(f"Wrote {VALIDATION_PATH} and {REVIEW_PATH}.")


def import_review():
    with REVIEW_PATH.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    records = []
    for row in rows:
        decision = row["decision"].strip().casefold()
        if decision not in {"accept", "correct", "reject"}:
            raise ValueError(f"{row['id']} must be marked accept, correct, or reject.")
        if decision == "reject":
            continue
        standard = row["proposed_standard"].strip() or None
        clause = row["proposed_clause"].strip() or None
        if decision == "correct":
            standard = row["corrected_standard"].strip() or None
            clause = row["corrected_clause"].strip() or None
        if bool(standard) != bool(clause):
            raise ValueError(f"{row['id']} has an incomplete corrected match.")
        records.append({
            "id": row["id"],
            "requirement": row["requirement"],
            "expected_standard": standard,
            "expected_clause": clause,
            "category": row["category"],
        })
    if len(records) != 48:
        raise ValueError(f"Final test needs 48 accepted/corrected rows; found {len(records)}.")
    _write_jsonl(TEST_PATH, records)
    digest = hashlib.sha256(TEST_PATH.read_bytes()).hexdigest()
    TEST_MANIFEST_PATH.write_text(json.dumps({
        "test_sha256": digest,
        "record_count": len(records),
        "reviewed": True,
    }, indent=2), encoding="utf-8")
    print(f"Frozen test set: {digest}")


def main():
    parser = argparse.ArgumentParser(description="Prepare Phase 2B RAG evaluation data.")
    parser.add_argument("--import-review", action="store_true")
    args = parser.parse_args()
    import_review() if args.import_review else create_review_files()


if __name__ == "__main__":
    main()
