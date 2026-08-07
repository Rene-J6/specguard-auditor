# Project Status

- **Last updated:** 2026-08-07
- **Branch:** `main`, one local commit ahead of `origin/main`
- **Overall status:** In Progress
- **Current goal:** Restrict document upload and extraction to digital PDFs only.
- **Next immediate task:** Remove runtime OCR and enforce digital-PDF validation.
- Phase 2B clause-aware RAG is active; tracked changes are ready to commit.

# Project Overview

SpecGuard is a local-first English Software Requirements Specification auditing platform.

It extracts document text, detects requirement statements, retrieves relevant local standards,
uses a local LLM to analyse and rewrite requirements, supports Expert review, and exports
approved examples for manually initiated fine-tuning.

Current stack:

- React, Vite, and TailwindCSS frontend.
- FastAPI backend.
- SQLite authentication and audit databases.
- ChromaDB and BGE-M3 standards retrieval.
- EasyOCR, OpenCV, and pdfplumber extraction.
- 4-bit Llama-3-8B with an Unsloth LoRA adapter.
- Local Windows deployment on an RTX 4060 Laptop GPU with 8 GB VRAM.

# Current Architecture

Important modules:

- `app/main.py`: API routes and audit orchestration.
- `app/database.py`: authentication data, audit lifecycle, and training export.
- `app/security.py`: HttpOnly-cookie authentication and role authorization.
- `app/utils.py`: extraction and structure-preserving text cleaning.
- `app/requirement_detector.py`: Phase 2A segmentation and requirement classification.
- `app/retrieval.py`: Phase 2B local embeddings and scored Top-K retrieval.
- `app/model_engine.py`: Llama, OCR, and runtime vector-store loading.
- `scripts/ingest_rag.py`: deterministic clause-aware candidate-index builder.

AI pipeline:

```text
Upload
  -> extraction and cleaning
  -> structure-aware segmentation
  -> MiniLM + Logistic Regression requirement detection
  -> BGE-M3 standards retrieval
  -> local Llama analysis and rewrite
  -> Expert review
  -> canonical training dataset
  -> manual fine-tuning
```

Stable decisions:

- No cloud inference or cloud document processing.
- Gemini is allowed only in manually run synthetic-data scripts.
- Fine-tuning remains manual.
- Canonical training fields remain `bad_requirement`, `document_reference`, `analysis`, and `suggested_rewrite`.
- Lifecycle remains `PENDING -> LOCKED -> APPROVED | REJECTED`.
- One active document lock per Expert.
- Expert approval is final; Admin manages accounts and records but does not approve content.
- User history must not expose lifecycle, reviewer, or training-export metadata.
- Runtime RAG is fixed at `k=5`; only Top 1 evidence is sent to Llama.
- No RAG hard threshold or reranker is enabled in Phase 2B.

# Completed in This Session

- Added deterministic clause/section-aware ingestion for all five knowledge PDFs.
- Added a strict source manifest with canonical standard names and parser modes.
- Added numbered-heading support for inline and split-line PDF headings.
- Added controlled section/page fallback for policy documents.
- Added repeated margin removal and long-clause secondary splitting.
- Added canonical metadata: standard, clause, title, source, pages, part indexes, and source hash.
- Added SHA-256 chunk IDs and deterministic exact-duplicate removal.
- Added a candidate cosine Chroma collection named `standards_v2`.
- Kept BGE-M3 CPU-only, local-only, and normalized for the candidate index.
- Added an independent retrieval contract returning Top-K candidates, raw distance, and score.
- Runtime now requests five candidates and sends only Top 1 to the existing LLM flow.
- Added compatibility loading for the current legacy index and future clause index.
- Added baseline/candidate evaluation tooling and owner-review test workflow.
- Added 48 validation rows and 48 independent proposed final-test rows.
- Added ingestion, retrieval, and evaluation unit tests.
- Updated README Phase 2B commands and limitations.

Files added:

- `app/retrieval.py`
- `data/knowledge_base/sources.json`
- `data/knowledge_base/index_manifest.json`
- `data/rag_evaluation/validation.jsonl`
- `data/rag_evaluation/test_review.csv`
- `scripts/prepare_rag_evaluation.py`
- `scripts/evaluate_rag.py`
- `tests/test_rag_ingestion.py`
- `tests/test_rag_retrieval.py`
- `tests/test_rag_evaluation.py`

Files modified:

- `.gitignore`
- `app/main.py`
- `app/model_engine.py`
- `scripts/ingest_rag.py`
- `README.md`
- `HANDOFF.md`

# Current State

Verified working:

- Clause-aware index is active at ignored `data/knowledge_base/chroma_db/`.
- The legacy index is backed up at `data/knowledge_base/chroma_backup_20260808_pre_phase2b/`.
- Candidate contains 1,210 unique clause-aware chunks.
- Industry4WRD produced 220 chunks and removed 22 exact duplicates.
- ISO 9001 produced 104 chunks.
- ISO/IEC 25010 produced 147 chunks.
- ISO/IEC/IEEE 29148 produced 355 chunks.
- Malaysia Digital Economy Blueprint produced 384 chunks and removed 3 exact duplicates.
- Candidate collection uses cosine distance and normalized 1,024-dimensional BGE-M3 embeddings.
- New RAG unit tests: 12/12 passed.
- Full regression suite completed without failure.
- `git diff --check` passed; only line-ending warnings remain.

Validation findings:

- Corrected same-set baseline: Hit@1 0%, Hit@3 7.5%, Hit@5 10%, MRR 0.038.
- Clause-aware candidate: Hit@1 5%, Hit@3 10%, Hit@5 15%, MRR 0.082.
- Candidate improves ranking but remains too weak for a reliable relevance threshold.
- No tested threshold reached the planned 90% validation Hit@5 gate.
- Owner chose fixed `k=5` with no hard threshold; weak matches are documented as a constraint.
- Average candidate validation retrieval was about 183 ms per requirement on CPU.

Still incomplete:

- `test_review.csv` remains an optional, unreviewed future evaluation set.
- Runtime OCR and image upload support still need removal.
- Digital-PDF type, signature, and minimum-text validation are not yet enforced.

# Known Issues / Technical Debt

- Fixed Top-K always returns a candidate when the index is non-empty, so unrelated requirements can receive weak clauses.
- BGE semantic similarity alone does not reliably map domain-specific functional requirements to abstract standards clauses.
- Candidate improvement is modest; current results must not be presented as high retrieval accuracy.
- The evaluation set may contain legitimate alternative clauses across ISO 25010 and ISO 29148.
- No reranker is included; add one only if later evidence shows the correct clause is already in a wider candidate pool.
- Full PDF parsing takes several minutes; Industry4WRD is the slowest source.
- Full BGE-M3 CPU ingestion is intentionally slow and uses about 3.6 GB RAM during build.
- OCR is not used during knowledge-base ingestion; scanned standards would still fail extraction.
- Policy PDFs contain graphical/multi-column text and noisy reading order.
- Active Chroma replacement requires the backend to be stopped on Windows.
- Chroma and JSONL/SQLite storage cannot share a cross-system atomic transaction.
- Phase 2A synthetic data may not represent real SRS language.
- Scanned and mixed user PDFs still lack reliable page-level OCR rasterisation.
- The requirement-detector and RAG model directories are ignored by Git and must be copied or rebuilt.
- README still contains some legacy setup wording and terminal mojibake.

# Next Priorities

1. Commit the active Phase 2B RAG changes.
2. Accept digital PDFs only and remove runtime OCR/image support.
3. Run a real digital-SRS User-to-Expert-to-Admin smoke test.
4. Prepare fixed demo documents and document the accepted retrieval constraints.
5. Correct remaining README setup inconsistencies and mojibake.

# Pitfalls / Lessons Learned

- Work from `C:\Users\JUN KIAT\Desktop\FYP`; the Documents folder is not the main checkout.
- Use `C:\Users\JUN KIAT\anaconda3\envs\FYP\python.exe`.
- Do not run ingestion while the backend has the active Chroma database open.
- Never build directly into `chroma_db`; build and validate `chroma_candidate` first.
- Do not claim a threshold is validated when the validation gate failed.
- Do not tune against the future frozen RAG final test.
- Do not reuse the spent Phase 2A frozen test for model selection.
- BGE-M3 must remain CPU-only to preserve GPU memory for Llama and EasyOCR.
- Keep Hugging Face/Transformers offline flags enabled for local BGE loading.
- Do not re-enable Uvicorn reload around Unsloth-generated files.
- Do not append `instruction/output` records to the canonical training JSONL.
- Do not trigger automatic fine-tuning.

# Notes for the Next Session

- Read `AGENTS.md`, `HANDOFF.md`, and `README.md` first.
- Review `app/retrieval.py`, `scripts/ingest_rag.py`, and the candidate manifest first.
- Preserve the active clause-aware index and its legacy rollback backup.
- Preserve fixed `k=5`, no hard threshold, and Top-1-only LLM context unless a new decision is approved.
- Treat retrieval scores as ranking signals, not calibrated probabilities.
- Chroma directories are ignored by Git; a fresh checkout must rebuild the index.
- Ask before database-schema, role-workflow, API-contract, or AI-pipeline changes.
- Update this document after activation or any new evaluation decision.
