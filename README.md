# 🛡️ SpecGuard: Local AI Requirements Audit Platform

SpecGuard is a sovereign, local-first compliance auditing platform for software requirements documents. It combines digital-PDF text extraction, semantic rule retrieval, and a fine-tuned local LLM to analyze, audit, and improve requirements against standards such as:

- ISO/IEC/IEEE 29148
- ISO/IEC 25010
- ISO 9001
- Industry4WRD
- MyDIGITAL

The system is designed for offline operation with private data, using local SQLite storage and fine-tuned models on consumer hardware.

---

## 🚀 What This Project Does

- Accepts digital PDF specification documents via a web UI
- Extracts selectable PDF text locally with `pdfplumber`
- Identifies requirement statements with a local MiniLM + Logistic Regression classifier and keyword fallback
- Retrieves related standard clauses from a local Chroma vector store
- Generates validated, structured analysis and rewrite suggestions using a fine-tuned local LLM
- Logs audit results for user history, expert review, and admin lifecycle management
- Supports three roles: `User`, `Expert`, and `Admin`

---

## 🧠 Architecture Overview

### Backend

Implemented in `app/` using FastAPI:

- `app/main.py` — REST endpoints for session auth, document upload, audit execution, expert workflows, notifications, reports, and administration
- `app/model_engine.py` — Loads the fine-tuned LoRA model, embedding model, and Chroma retrieval store
- `app/database.py` — SQLite migrations, sessions, user management, audit logging, expert review flows, notifications, and dataset export support
- `app/security.py` — HttpOnly-cookie session resolution and server-side role authorization
- `app/reporting.py` — Owner-scoped DOCX audit report generation
- `app/requirement_detector.py` — Structure-aware segmentation, local ML detection, and keyword fallback
- `app/audit_output.py` — Structured audit schema, grounding validation, controlled repair, retry, and legacy parsing
- `app/utils.py` — Digital-PDF extraction and text-cleaning helpers

### Frontend

Implemented in `frontend/` using React + Vite + Tailwind CSS:

- `frontend/src/App.jsx` — Main application UI with login/register flow, upload and analysis workspace, history viewer, expert queue/editor, notifications, and admin console
- `frontend/package.json` — Frontend dependencies and scripts

### Models & Knowledge Base

- `models/finetuned/sirim_specialist_lora/` — Local fine-tuned LoRA adapter weights and tokenizer
- `models/requirement_detector/` — Local MiniLM encoder, Logistic Regression classifier, and activation metadata
- `data/knowledge_base/chroma_db/` — Persisted Chroma DB for semantic retrieval
- `data/requirement_detection/` — Detection train/validation data and the manually reviewed test workflow
- `data/training/dataset.jsonl` — Training dataset collected from expert validation and synthetic generation

---

## 📦 Dependencies

### Python backend

Dependencies are declared in `requirements.txt`. Key packages include:

- `fastapi`, `uvicorn`
- `pydantic`, `python-multipart`
- `pdfplumber`, `python-docx`
- `langchain-huggingface`, `langchain-chroma`, `langchain-community`
- `sentence-transformers`, `scikit-learn`, `chromadb`
- `unsloth`, `trl`, `peft`, `accelerate`, `bitsandbytes`
- `pandas`, `openpyxl`, `python-dotenv`
- `werkzeug`

### Frontend

- `react`, `react-dom`
- `vite`
- `tailwindcss`
- `eslint`

---

## 🛠️ Setup & Run

### 1. Install Python dependencies

From the repository root:

```bash
pip install -r requirements.txt
```

### 2. Prepare the local workspace

```bash
python scripts/data_generator.py
```

### 3. Ingest the knowledge base

Place compliance PDFs into `data/knowledge_base/` and run:

```bash
python scripts/ingest_rag.py
```

This generates the local Chroma DB at `data/knowledge_base/chroma_db`.

### 4. Train or verify the model

To fine-tune a local adapter:

```bash
python scripts/fine_tune_local.py
```

To verify the saved model adapter:

```bash
python scripts/test_model.py
```

### Digital PDF input

User uploads are limited to `.pdf` files with MIME type `application/pdf`, a
valid `%PDF-` signature, and at least 50 extractable non-whitespace characters.
Images, corrupted PDFs, and image-only scanned PDFs are rejected. Runtime OCR is
not loaded.

Mixed PDFs are accepted when their combined selectable text reaches the minimum.
Image-only pages inside such a file are not detected or extracted; this is an
accepted local-project constraint.

### Phase 2A requirement detector

The requirement detector is independent from RAG and the Llama audit model. It
uses CPU-only `all-MiniLM-L6-v2` embeddings and Logistic Regression. If the
local artifact is missing, disabled, corrupt, or fails during inference, the
original modal-keyword detector processes the whole document batch instead.

Generate two synthetic development pilot batches manually; Gemini is never
imported by the backend and no user document is sent to it:

```bash
python scripts/generate_requirement_detection_data.py --mode dev --start 1 --batches 2
```

Inspect the pilot before expanding the development pool and preparing the
1,400/300 split:

```bash
python scripts/generate_requirement_detection_data.py --mode dev --start 3 --batches 42
python scripts/prepare_requirement_detection_data.py prepare-development --input-dir outputs/requirement_detection/generated/dev
```

Generate independent test candidates and export the Excel-compatible review
CSV:

```bash
python scripts/generate_requirement_detection_data.py --mode test --start 1 --batches 9
python scripts/prepare_requirement_detection_data.py export-review --input-dir outputs/requirement_detection/generated/test
```

Exact/near deduplication can reduce either pool. If preparation reports too few
independent samples, generate new consecutively numbered top-up batches and
rerun the same preparation command.

In `data/requirement_detection/test_review.csv`, set every `decision` to
`accept`, `relabel`, or `reject`. Relabelled rows also require
`corrected_label` and `corrected_category`. Then freeze the balanced test set,
train a disabled candidate, and run the one-time final evaluation:

```bash
python scripts/prepare_requirement_detection_data.py freeze-test
python scripts/train_requirement_detector.py
python scripts/evaluate_requirement_detector.py --activate
```

`--activate` only enables the artifact when frozen-test recall is at least 90%
and its F1 is higher than the keyword baseline. The frozen test set must never
be used for training, threshold selection, or repeated model selection.

Current local Phase 2A checkpoint:

- 1,400 training and 300 validation rows, each exactly 50/50.
- Validation threshold `0.6`: accuracy `0.940`, precision `0.952`, recall
  `0.927`, F1 `0.939`.
- The owner accepted all 337 independent candidates; 300 balanced rows were
  frozen with SHA-256
  `e638b4b7997d0d156d56463727be8f9a35522929bdb1b87a896a0ff8a18f19d2`.
- Frozen-test keyword baseline: accuracy `0.590`, recall `0.460`, F1 `0.529`.
- Frozen-test ML classifier: accuracy `0.910`, precision `0.924`, recall
  `0.893`, F1 `0.908`, with 11 false positives and 16 false negatives.
- The activation gate failed because recall was below 90%. The project owner
  explicitly accepted the 89.33% result, so the threshold-0.6 artifact is
  enabled through a documented manual override.
- Do not tune against or reuse this frozen test for another activation decision.

### Phase 2B standards retrieval

Phase 2B keeps the existing local CPU-only BGE-M3 embedding model and replaces
character chunks with clause/section-aware chunks. The source manifest is
`data/knowledge_base/sources.json`; every PDF must be listed before ingestion.

Build a deterministic candidate index without touching the active index:

```bash
python scripts/ingest_rag.py
```

Use `--prepare-only` to validate parsing and deterministic IDs without loading
BGE-M3. The candidate is written to the ignored
`data/knowledge_base/chroma_candidate/` directory. Its tracked summary is
`data/knowledge_base/index_manifest.json`.

Prepare the validation set and owner-review CSV:

```bash
python scripts/prepare_rag_evaluation.py
```

After every row in `data/rag_evaluation/test_review.csv` is marked `accept`,
`correct`, or `reject`, freeze the 48-row test set:

```bash
python scripts/prepare_rag_evaluation.py --import-review
```

Evaluate the existing baseline and clause-aware candidate on the same dataset:

```bash
python scripts/evaluate_rag.py data/rag_evaluation/test.jsonl --method baseline
python scripts/evaluate_rag.py data/rag_evaluation/test.jsonl --method candidate --no-threshold
```

Runtime retrieval is deliberately fixed at `k=5`. It preserves five scored
candidates internally and sends only Top 1 to the LLM. No hard score threshold
is enabled because current validation could not establish a reliable cutoff;
weakly related Top-1 matches are a documented limitation. Reranking is not part
of this version.

The clause-aware index is active at `data/knowledge_base/chroma_db/`. The
pre-Phase-2B index is retained locally as
`data/knowledge_base/chroma_backup_20260808_pre_phase2b/` for rollback.

### Phase 2C structured audit output

New audits use a Pydantic-validated schema with a compliance status, controlled
issue tags, a server-owned standard reference, a grounded evidence excerpt,
an explanation, and a suggested rewrite. Retrieval remains fixed at `k=5`, and
only Top 1 is supplied to the LLM as evidence `E1`.

The backend, rather than the model, supplies the standard name, clause, title,
and source. Generated evidence must occur in E1 after whitespace normalization.
Invalid output receives at most one deterministic retry; a second failure is
stored and displayed as a safe `insufficient_evidence` result. Existing
Markdown audit records remain readable through the shared legacy parser.

The current LoRA was trained for Markdown rather than JSON. Runtime therefore
uses an assistant `{` prefix and a constrained repair path for JSON-like Python
dictionaries and the exact legacy Markdown format. Repair cannot introduce a
new citation: it replaces evidence and reference metadata with the retrieved E1
values and revalidates the complete result. This compatibility path is a known
constraint, not a substitute for future structured-output fine-tuning.

Run the fixed 48-case comparison without writing to the audit database:

```bash
python scripts/evaluate_audit_output.py
```

Use `--reuse-baseline` to retain the saved free-form baseline and rerun only the
structured approach. Current automatic results are:

- Free-form baseline parser success: `100%`; missing rewrite: `0%`.
- Structured first-attempt native JSON: `47.92%`; final native JSON: `52.08%`.
- Structured schema validation after controlled repair/retry: `97.92%`.
- Retry rate: `10.42%`; safe-failure rate: `2.08%`.
- Controlled-repair rate: `89.58%`.
- Average latency: baseline `14.32 s`, structured `14.27 s` per requirement.

These metrics are descriptive and are not an activation gate. The structured
implementation remains enabled even when the model output needs repair. Complete
the empty 0/1/2 quality scores in
`data/audit_evaluation/manual_review.csv` before claiming semantic improvement
over the baseline in the FYP report.

Evaluate the saved structured RAG outputs for faithfulness and answer relevance:

```bash
python scripts/evaluate_rag_generation.py
```

This offline utility re-verifies that every saved output still matches the current
Top-1 standard and clause, then uses Gemini 2.5 Flash as an evaluation-only judge.
It sends only the fixed synthetic requirements and their retrieved excerpts; the
runtime application remains local and never sends uploaded user documents. Use
`--prepare-only` to create the blinded 15-case Expert sheet without calling Gemini,
or `--summarize-only` after Expert scoring to regenerate agreement results.

Current automated judge results over all 48 cases are descriptive and await Expert
validation:

- Faithfulness mean: `0.542`; median: `0.750`.
- Answer-relevance mean: `0.740`; median: `1.000`.
- Judge errors: `0/48`.
- Expert validation: pending; all 15 blinded score rows remain empty.

Structural validation, retrieval Hit@K/MRR, and semantic generation scores remain
separate in `data/audit_evaluation/generation_quality_summary.md`. The existing
free-form baseline also receives retrieved evidence, so these results do not show
that RAG outperforms a non-RAG model.

The audit stream retains the existing `analysis` and `suggested_rewrite` keys
and adds the full result under `audit`. Experts may edit only the explanation
and rewrite. The database schema and four-field fine-tuning export schema are
unchanged.

### 5. Start the backend API

```bash
python main.py
```

Do not enable Uvicorn reload around the Unsloth-generated cache files.

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Then open the local Vite URL shown in the terminal.

---

## 🔧 User Workflows

### Standard user

1. Register or log in as a `User`
2. Upload a digital PDF with selectable text
3. Run the compliance audit
4. Review results and history
5. Export an owner-scoped DOCX audit report from document history

### Domain expert

1. Log in as an `Expert`
2. Claim one pending document set from the expert queue
3. Edit AI evaluations and rewrites
4. Approve submissions to export verified four-field dataset lines, reject them while retaining an audit record, or release the active document

An expert can hold only one active document lock. Documents locked by another expert are not available for review.

### Admin

1. Log in as an `Admin`
2. Create User, Expert, or Admin accounts and manage their roles/status
3. Monitor records grouped as `PENDING`, `LOCKED`, `APPROVED`, or `REJECTED`
4. Delete individual requirements or complete documents
5. When deleting approved data, remove its corresponding exported training record

Admins do not approve requirement content; expert approval is final. Internal lifecycle and export states are not exposed in standard user history.

### Authentication and account bootstrap

- Public registration always creates a `User`; only an Admin can create or promote Expert/Admin accounts.
- The API uses 12-hour server-side SQLite sessions in an HttpOnly cookie. Caller-provided usernames are not trusted for authorization.
- Disabled accounts cannot log in and existing sessions are revoked after role/status changes.
- Usernames are immutable because audit ownership is stored by username across the local databases.
- For a clean database with no Admin, run `python scripts/create_admin.py` once from the repository root. The command refuses to run when an active Admin already exists.

---

## 🗂️ File Structure

```text
FYP/
├── app/
│   ├── database.py
│   ├── main.py
│   ├── model_engine.py
│   ├── requirement_detector.py
│   └── utils.py
├── data/
│   ├── knowledge_base/
│   │   └── chroma_db/
│   ├── logs/
│   ├── temp/
│   ├── requirement_detection/
│   └── training/
│       └── dataset.jsonl
├── frontend/
│   ├── package.json
│   ├── README.md
│   └── src/
│       └── App.jsx
├── models/
│   └── finetuned/
│       └── sirim_specialist_lora/
├── outputs/
├── scripts/
│   ├── data_generator.py
│   ├── generate_requirement_detection_data.py
│   ├── prepare_requirement_detection_data.py
│   ├── train_requirement_detector.py
│   ├── evaluate_requirement_detector.py
│   ├── fine_tune_local.py
│   ├── ingest_rag.py
│   ├── setup_projects.py
│   └── test_model.py
├── storage/
│   ├── auth.db
│   └── training_pool.db
├── requirements.txt
└── README.md
```

---

## 💡 Notes

- The backend expects the fine-tuned adapter at `models/finetuned/sirim_specialist_lora/`.
- The vector store expects the Chroma database at `data/knowledge_base/chroma_db/`.
- GPU memory optimizations are already applied via `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
- Core audit workflows are designed for local offline operation.

---

## 📄 License

Add your license information here.
