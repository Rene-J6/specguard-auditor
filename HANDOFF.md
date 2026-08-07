# Project Status

- **Last updated:** 2026-08-08
- **Branch:** `main`, three local commits ahead of `origin/main` after this session.
- **Overall status:** In Progress
- **Current goal:** Stabilize the end-to-end FYP demo using real digital SRS PDFs.
- **Next immediate task:** Run a User-to-Expert-to-Admin smoke test with a real digital SRS supplied by the owner.
- Phase 2B clause-aware RAG is active.
- User uploads are intentionally limited to digital PDFs with selectable text.

# Project Overview

SpecGuard is a local-first English Software Requirements Specification auditing platform.

It extracts selectable PDF text, detects software requirements, retrieves related local
standards, uses a local LLM to analyse and rewrite requirements, supports Expert review,
and exports approved examples for manually initiated fine-tuning.

Current stack:

- React, Vite, and TailwindCSS frontend.
- FastAPI backend.
- SQLite authentication and audit databases.
- ChromaDB and CPU-only BGE-M3 standards retrieval.
- `pdfplumber` digital-PDF extraction; no runtime OCR.
- 4-bit Llama-3-8B with an Unsloth LoRA adapter.
- Local Windows deployment on an RTX 4060 Laptop GPU with 8 GB VRAM.

# Current Architecture

Important modules:

- `app/main.py`: API routes, upload validation, and audit orchestration.
- `app/database.py`: authentication data, lifecycle, and training export.
- `app/security.py`: HttpOnly-cookie authentication and role authorization.
- `app/utils.py`: digital-PDF extraction and text cleaning.
- `app/requirement_detector.py`: segmentation and requirement classification.
- `app/retrieval.py`: local BGE-M3 embeddings and scored Top-K retrieval.
- `app/model_engine.py`: Llama and active vector-store loading.
- `scripts/ingest_rag.py`: deterministic clause-aware index builder.

AI pipeline:

```text
Digital PDF
  -> selectable-text extraction
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
- No image upload, scanned-PDF OCR, or runtime OCR model.
- Mixed PDFs are accepted based on total extracted text; scanned pages may be ignored.
- Fine-tuning remains manual.
- Training fields remain `bad_requirement`, `document_reference`, `analysis`, and `suggested_rewrite`.
- Lifecycle remains `PENDING -> LOCKED -> APPROVED | REJECTED`.
- One active document lock per Expert.
- Expert approval is final; Admin manages accounts and records but does not approve content.
- User history must not expose lifecycle, reviewer, or training-export metadata.
- RAG is fixed at `k=5`; only Top 1 evidence is sent to Llama.
- No RAG hard threshold or reranker is enabled.

# Completed in This Session

## Phase 2B RAG

- Activated the validated `standards_v2` clause-aware Chroma index.
- Backed up the legacy index at `chroma_backup_20260808_pre_phase2b`.
- Active index contains 1,210 deterministic, unique chunks from five sources.
- BGE-M3 remains local-only, normalized, and CPU-only.
- Runtime keeps five scored candidates internally and sends Top 1 to Llama.
- Preserved legacy-index compatibility and rollback behavior.
- Kept the 48-row RAG test-review CSV as optional future evaluation work.
- Committed as `6e151e8 Improve clause-aware RAG retrieval`.

## Digital PDF only

- Removed EasyOCR initialization and the runtime OCR resource.
- Removed OpenCV/PaddleOCR/Pillow direct requirements.
- Replaced PDF/image extraction with `pdfplumber` digital-PDF extraction.
- Preserved page order using structural newlines between pages.
- Enforced `.pdf`, `application/pdf`, and `%PDF-` signature checks.
- Required at least 50 non-whitespace extractable characters.
- Added explicit 415, 400, and 422 error behavior.
- Replaced user filenames with safe random temporary paths.
- Updated frontend file acceptance and upload guidance.
- Updated upload, extraction, mixed-PDF, corruption, and path-safety tests.

Files modified for digital-PDF-only behavior:

- `app/main.py`
- `app/model_engine.py`
- `app/utils.py`
- `frontend/src/App.jsx`
- `requirements.txt`
- `tests/test_api_authorization.py`
- `tests/test_requirement_detector.py`
- `README.md`
- `HANDOFF.md`

# Current State

Verified working:

- Active Chroma collection: `standards_v2`, 1,210 vectors, cosine, 1,024 dimensions.
- Source hashes match the active index manifest.
- Local Top-5 retrieval smoke completed for functional, performance, and security samples.
- A real repository digital PDF extracted 57,731 characters successfully.
- Full Uvicorn startup reached `Application startup complete` without loading EasyOCR.
- `/openapi.json` returned HTTP 200, and the temporary server process was stopped cleanly.
- Full Python regression suite: 67/67 passed.
- Frontend ESLint passed.
- Frontend production build passed.
- Database schemas, lifecycle, authentication, reports, and training schema are unchanged.

Input behavior:

- Digital PDF with enough selectable text: accepted.
- PNG/JPG or any non-PDF input: HTTP 415.
- PDF extension/MIME with a non-PDF signature: HTTP 415.
- Corrupt PDF: HTTP 400.
- Image-only or text-insufficient PDF: HTTP 422.
- Mixed PDF with at least 50 extracted characters: accepted; scanned pages may be omitted.

# Known Issues / Technical Debt

- Fixed Top-K always returns a candidate from a non-empty index, including weak matches.
- Candidate validation improved over baseline but Hit@5 remained only 15%.
- Retrieval scores are ranking signals, not calibrated confidence.
- Domain-specific requirements do not always map cleanly to abstract standards clauses.
- No real SRS PDF exists in the repository, so the final company-style demo remains unverified.
- Mixed PDFs can silently omit image-only pages by explicit product decision.
- Strict MIME checking may reject clients that incorrectly send PDFs as `application/octet-stream`.
- Upload size is not yet limited.
- Knowledge-base ingestion remains slow because BGE-M3 runs on CPU.
- Chroma indexes and local model artifacts are ignored by Git and must be rebuilt or copied.
- Phase 2A synthetic language may differ from real SRS language.
- README still contains some legacy setup wording and terminal mojibake.
- `frontend/src/App.jsx` remains monolithic; refactor only if it blocks demo work.

# Next Priorities

1. Commit the digital-PDF-only changes.
2. Obtain one representative real digital SRS PDF from the owner.
3. Run User upload/analysis/history/report through the real document.
4. Run Expert claim/edit/approve or reject and verify the User comparison.
5. Verify Admin records and user-management views after the same workflow.
6. Prepare one small fixed demo PDF with known expected requirements.
7. Record observed detector/RAG errors as FYP limitations, not hidden failures.
8. Correct remaining README/setup mojibake before final presentation.

# Pitfalls / Lessons Learned

- Work from `C:\Users\JUN KIAT\Desktop\FYP`; the Documents folder is not the checkout.
- Use `C:\Users\JUN KIAT\anaconda3\envs\FYP\python.exe`.
- Start backend with `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Do not reintroduce OCR or image upload unless the product scope changes explicitly.
- `AGENTS.md` still lists the historical OCR stack; README/HANDOFF reflect the newer product decision.
- Do not claim that mixed-PDF scanned pages were processed.
- Do not run ingestion while the backend has Chroma open.
- Preserve `chroma_backup_20260808_pre_phase2b` until the final demo is stable.
- Never build directly into the active index; build a candidate first.
- Keep BGE-M3 on CPU to preserve GPU memory for Llama.
- Do not re-enable Uvicorn reload around Unsloth-generated files.
- Do not append `instruction/output` records to the canonical training JSONL.
- Do not trigger automatic fine-tuning.

# Notes for the Next Session

- Read `AGENTS.md`, `HANDOFF.md`, and `README.md` first.
- Confirm the active index and legacy backup both exist before RAG work.
- Use only digital PDFs with selectable text for upload tests.
- Preserve fixed `k=5`, no threshold, and Top-1-only LLM context.
- Treat `test_review.csv` as optional future evaluation, not an activation gate.
- Do not modify database schema, role workflow, API response shape, or training schema.
- Update this document after the real-SRS end-to-end demo.
