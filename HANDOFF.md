# Project Status

- Last updated: 2026-08-20.
- Branch: `main`.
- HEAD before current uncommitted work: `2420d1a Restrict uploads to digital PDFs`.
- Branch is three commits ahead of `origin/main`.
- Overall status: In Progress.
- Current development goal: complete human validation of Phase 2C generation quality.
- Next immediate task: have one Expert score the blinded 15-case faithfulness and answer-relevance sheet.
- Phase 2C implementation is intentionally retained without an activation gate.

# Project Overview

SpecGuard is a local-first English Software Requirements Specification auditing platform.

It accepts digital PDFs with selectable text, detects requirements, retrieves related
standards, uses a local Llama model to audit and rewrite requirements, supports Expert
review, and exports approved examples for manually initiated fine-tuning.

Current stack:

- React, Vite, and TailwindCSS frontend.
- FastAPI backend.
- SQLite authentication and audit databases.
- ChromaDB with CPU-only BGE-M3 retrieval.
- `pdfplumber` extraction; no runtime OCR.
- CPU-only MiniLM and Logistic Regression requirement detector.
- 4-bit Llama-3-8B with an Unsloth LoRA adapter.
- Local Windows deployment on an RTX 4060 Laptop GPU with 8 GB VRAM.

# Current Architecture

Important modules:

- `app/main.py`: API routes, upload validation, model generation, and audit orchestration.
- `app/audit_output.py`: Phase 2C schema, prompt, validation, repair, retry, and legacy parsing.
- `app/database.py`: authentication, lifecycle, notifications, and training export.
- `app/security.py`: HttpOnly-cookie authentication and role authorization.
- `app/reporting.py`: owner-scoped DOCX audit reports.
- `app/utils.py`: digital-PDF extraction and text cleaning.
- `app/requirement_detector.py`: segmentation, ML classification, and keyword fallback.
- `app/retrieval.py`: local BGE-M3 embeddings and scored Top-K retrieval.
- `app/model_engine.py`: Llama and active Chroma-store loading.
- `frontend/src/App.jsx`: current monolithic User, Expert, and Admin UI.

AI pipeline:

```text
Digital PDF
  -> selectable-text extraction
  -> structure-aware segmentation
  -> MiniLM + Logistic Regression requirement detection
  -> BGE-M3 retrieval (k=5)
  -> Top 1 evidence supplied to local Llama
  -> structured audit validation and controlled repair
  -> Expert review
  -> canonical four-field training dataset
  -> manual fine-tuning
```

Locked design decisions:

- No cloud inference or cloud document processing.
- No OCR, image upload, or scanned-PDF support.
- Mixed PDFs are accepted by total extracted text; scanned pages may be ignored.
- RAG remains fixed at `k=5`; only Top 1 is sent to Llama.
- No RAG hard threshold or reranker.
- Fine-tuning remains manual.
- Training fields remain `bad_requirement`, `document_reference`, `analysis`, and `suggested_rewrite`.
- Lifecycle remains `PENDING -> LOCKED -> APPROVED | REJECTED`.
- One active document lock per Expert.
- Expert approval is final; Admin manages accounts and records but does not approve content.
- User history must not expose lifecycle, reviewer, or training-export metadata.
- No database migration was introduced for Phase 2C.

# Completed in This Session

Phase 2C structured audit output was implemented:

- Added Pydantic-controlled compliance statuses, issue tags, references, and evidence.
- Added exact normalized evidence grounding against the retrieved Top 1 clause, identified as `E1`.
- Made standard, clause, title, and source server-owned instead of model-generated.
- Added deterministic JSON prompting with an assistant `{` prefix.
- Added one retry for invalid output and a safe `insufficient_evidence` fallback.
- Added controlled repair for JSON-like Python dictionaries and exact legacy Markdown output.
- Revalidated every repaired result before storage or streaming.
- Preserved existing stream keys and added the structured result under `audit`.
- Stored new `model_output` values as canonical JSON without changing the database schema.
- Added a shared parser for structured JSON, legacy Markdown, and malformed historical output.
- Kept Expert editing limited to explanation and suggested rewrite.
- Added status badges, issue tags, standard metadata, evidence, and safe-failure warnings to the UI.
- Preserved four-field Expert-approved training exports.
- Added a fixed 48-case baseline-versus-structured evaluator and manual-review CSV.
- Added a separate 48-case Gemini judge for faithfulness and answer relevance.
- Added a deterministic, blinded 15-case Expert-validation sheet covering all nine categories.
- Kept structural reliability, retrieval quality, and semantic generation results separate.

Files added:

- `app/audit_output.py`
- `scripts/evaluate_audit_output.py`
- `scripts/evaluate_rag_generation.py`
- `tests/test_audit_output.py`
- `tests/test_rag_generation_evaluation.py`
- `data/audit_evaluation/cases.jsonl`
- `data/audit_evaluation/evaluation.json`
- `data/audit_evaluation/evaluation.md`
- `data/audit_evaluation/manual_review.csv`
- `data/audit_evaluation/generation_quality_judge.jsonl`
- `data/audit_evaluation/generation_quality_expert_review.csv`
- `data/audit_evaluation/generation_quality_summary.json`
- `data/audit_evaluation/generation_quality_summary.md`

Files modified:

- `app/main.py`
- `app/database.py`
- `frontend/src/App.jsx`
- `tests/test_api_authorization.py`
- `tests/test_database_lifecycle.py`
- `tests/test_report_export.py`
- `README.md`
- `HANDOFF.md`

# Current State

Verified working:

- Full Python regression suite: 91/91 passed.
- Frontend ESLint passed.
- Frontend production build passed.
- Audit stream remains backward compatible and adds `audit`.
- New audits are validated before database logging.
- Legacy Markdown records still display through the shared parser.
- User history, comparison, Expert review, DOCX reports, authorization, and lifecycle tests pass.
- Database schema, RAG behavior, requirement detector, authentication, and training schema are unchanged.

Final automatic 48-case evaluation:

- Baseline parser success: 100%; missing rewrite: 0%.
- Structured first-attempt native JSON: 47.92%.
- Structured final native JSON: 52.08%.
- Structured schema validation after repair/retry: 97.92%.
- Retry rate: 10.42%.
- Safe-failure rate: 2.08%.
- Controlled-repair rate: 89.58%.
- Unsupported-reference count: 0.
- Baseline average latency: 14.32 seconds per requirement.
- Structured average latency: 14.27 seconds per requirement.

Generation-quality judge evaluation:

- All 48 saved outputs matched the current Top-1 standard and clause before judging.
- Gemini judge completion: 48/48; errors: 0.
- Faithfulness mean: 0.542; median: 0.750.
- Answer-relevance mean: 0.740; median: 1.000.
- Expected-match and no-match results are reported separately.
- These results remain descriptive until the blinded Expert review is complete.

Still incomplete:

- The 48 manual 0/1/2 quality comparisons are unscored.
- The 15-case faithfulness and answer-relevance Expert sheet is unscored.
- Model-Expert exact agreement and quadratic weighted kappa are therefore pending.
- Semantic improvement over the free-form baseline must not be claimed until that review is complete.
- A real company-style digital SRS end-to-end smoke test is still pending.

# Known Issues / Technical Debt

- The LoRA was trained for Markdown, not structured JSON.
- Native valid JSON is only 52.08% after retry; most successful results use controlled repair.
- Controlled repair improves structural reliability but cannot prove semantic correctness.
- Exact evidence grounding proves text presence, not that RAG retrieved the correct clause.
- Fixed Top-K retrieval can return weak Top 1 evidence because no threshold is used.
- Safe failure preserves workflow but requires Expert attention.
- The 1,024-token model context can constrain long evidence and responses.
- Mixed PDFs may silently omit scanned pages by explicit product decision.
- Upload size is not limited.
- Local model and Chroma artifacts are ignored by Git and must be rebuilt or copied.
- `frontend/src/App.jsx` remains monolithic.
- README still contains terminal mojibake and some legacy setup wording.

# Next Priorities

1. Have one software-requirements Expert independently score all 15 blinded rows in `generation_quality_expert_review.csv`.
2. Run `python scripts/evaluate_rag_generation.py --summarize-only` to calculate model-Expert agreement.
3. Score the separate 48-row baseline-versus-structured sheet only if that comparison is needed in the report.
4. Run compliant, ambiguous, measurable, and weak-evidence manual smoke cases.
5. Run one real digital SRS through User upload, analysis, history, comparison, and DOCX export.
6. Complete Expert claim/edit/approve or reject and verify the User comparison.
7. Record detector, retrieval, judge, JSON-generation, and repair limitations in the FYP report.
8. Fix remaining README mojibake and setup inconsistencies before presentation.

# Pitfalls / Lessons Learned

- Work from `C:\Users\JUN KIAT\Desktop\FYP`; the Documents folder is not the checkout.
- Use `C:\Users\JUN KIAT\anaconda3\envs\FYP\python.exe`.
- Start backend with `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Do not use Uvicorn reload around Unsloth-generated files.
- Do not trust model-generated standards, clauses, or evidence references.
- Do not accept partial JSON or Markdown fences as native structured output.
- Do not remove legacy parsing while historical Markdown rows remain in the database.
- Do not describe 97.92% schema success as 97.92% audit-quality accuracy.
- Do not tune prompts or repair rules against the manual evaluation scores after review.
- Do not reintroduce OCR unless the product scope changes explicitly.
- Do not run RAG ingestion while the backend has Chroma open.
- Do not append `instruction/output` records to the canonical training JSONL.
- Do not trigger automatic fine-tuning.

# Notes for the Next Session

- Read `AGENTS.md`, `HANDOFF.md`, and `README.md` first.
- Review `app/audit_output.py`, `app/main.py`, and `scripts/evaluate_audit_output.py` first for Phase 2C work.
- Treat automatic evaluation results as descriptive, not an activation gate.
- Do not call the Gemini scores Expert-validated until all 15 blinded rows are scored.
- The judge utility is evaluation-only; never send uploaded user documents to it.
- Preserve the current implementation even if manual results are imperfect; report constraints honestly.
- Keep manual evaluation separate from prompt/model selection.
- Use only digital PDFs with selectable text for upload tests.
- Preserve fixed `k=5`, no threshold, and Top-1-only Llama context.
- Ask before architectural, database-schema, role-workflow, RAG, detector, or training-schema changes.
