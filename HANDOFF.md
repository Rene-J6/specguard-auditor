# Project Status

- **Last updated:** 2026-08-06
- **Current branch:** `main`
- **Application checkout:** `C:\Users\JUN KIAT\Desktop\FYP`
- **Overall status:** In Progress
- **Current goal:** Stabilize the enabled Phase 2A classifier and begin page-level hybrid OCR work.
- **Next immediate task:** Run a real-document classifier smoke test, then plan scanned/mixed-PDF OCR.
- **Important:** The enabled model artifact is local and ignored by Git; keep `models/requirement_detector/` with the checkout.

# Project Overview

SpecGuard is a local-first English Software Requirements Specification auditing platform.

It extracts document text, identifies requirement statements, retrieves relevant local standards, uses a local LLM to analyse and rewrite requirements, supports Expert review, and exports approved examples for manually initiated fine-tuning.

Current scope:

- React/Vite/Tailwind frontend and FastAPI backend.
- SQLite authentication and audit databases.
- Chroma with BGE-M3 embeddings for standards retrieval.
- 4-bit Llama-3-8B with an Unsloth LoRA adapter.
- Local Windows deployment on an RTX 4060 Laptop GPU with 8 GB VRAM.

# Current Architecture

## Main components

- Frontend: `frontend/src/App.jsx`.
- Backend routes and orchestration: `app/main.py`.
- Database lifecycle and training export: `app/database.py`.
- Extraction and cleaning: `app/utils.py`.
- Requirement segmentation/detection: `app/requirement_detector.py`.
- RAG and local LLM loading: `app/model_engine.py`.

## AI pipeline

```text
Upload
  -> extraction and structure-preserving cleaning
  -> sentence/paragraph segmentation
  -> requirement detection
  -> detected requirements only
  -> Chroma/BGE-M3 retrieval
  -> local LLM analysis and rewrite
  -> Expert review
  -> canonical training dataset
  -> manual fine-tuning
```

The Phase 2A detector is independent of RAG and the LLM:

- Preferred runtime: local `all-MiniLM-L6-v2` embeddings on CPU plus Logistic Regression.
- Fallback and evaluation baseline: the exact legacy modal-keyword substring detector.
- A failed/missing/disabled artifact keeps the backend running with keyword fallback.
- A whole inference batch falls back together; one document never mixes methods.

## Authentication and lifecycle

- Browser authentication uses a 12-hour HttpOnly cookie and hashed SQLite sessions.
- Identity and role come from the server-side session, not request usernames.
- Public registration creates User accounts only; Admin manages privileged accounts.
- Lifecycle remains `PENDING -> LOCKED -> APPROVED | REJECTED`.
- One active document lock is allowed per Expert.
- Expert approval is final; Admin manages users/records but does not approve content.
- User history and reports hide lifecycle, reviewer, and training-export metadata.

## Stable decisions

- No cloud inference or cloud document processing.
- Gemini is allowed only in the manually run synthetic-data script.
- Never send real SRS documents, audit records, or user data to Gemini.
- Fine-tuning remains manual.
- Canonical fine-tuning fields remain `bad_requirement`, `document_reference`, `analysis`, and `suggested_rewrite`.
- Do not change database schemas, role workflows, public API contracts, RAG, OCR, or LLM behaviour without approval.
- The frozen Phase 2A test set must never influence training, threshold selection, or model selection.

# Completed in This Session

## Runtime detector

- Added structure-aware segmentation for paragraphs, bullets, numbered items, wrapped lines, and sentence punctuation.
- Preserved document order, bullet/number prefixes, and original wording.
- Isolated the exact legacy keyword behaviour as baseline and fallback.
- Added CPU-only local artifact loading and ordered batch prediction.
- Integrated detector output into `/api/analysis/run` without changing its request or streaming response schema.
- Changed the empty-result message to `No requirements detected.`.
- Preserved structural newlines in `app/utils.py`; scanned-PDF rasterisation remains out of scope.

## Dataset pipeline

- Added a manual Gemini generator with ten balanced categories and deterministic local metadata.
- Added strict six-field JSONL validation and category/label/modal checks.
- Added Unicode-normalised exact deduplication and MiniLM cosine near-deduplication at 0.95.
- Added batch-grouped train/validation splitting and cross-split leakage detection.
- Added hash-protected CSV test review and frozen-test manifest generation.
- Generated 2,200 development candidates and 450 independent test candidates.
- Prepared 1,400 balanced training rows and 300 balanced validation rows.
- Exported 337 test-review candidates: 169 Requirement and 168 Non-requirement.
- Removed 161 exact and 236 near duplicates from development candidates.
- Removed test candidates that duplicated one another or were near development samples.

## Training and evaluation

- Added fixed CPU training for MiniLM embeddings and balanced Logistic Regression.
- Added validation-only threshold selection across 0.4, 0.5, and 0.6 with a 90% recall floor.
- Trained a local candidate with threshold 0.6.
- Validation metrics: accuracy 0.9400, precision 0.9521, recall 0.9267, F1 0.9392.
- Initially saved the candidate disabled; it was later enabled through the documented owner override below.
- Added same-test baseline/ML metrics, timing, slices, error files, and activation-gate tooling.
- The owner accepted all 337 review candidates; 300 balanced rows were frozen.
- Frozen test SHA-256: `e638b4b7997d0d156d56463727be8f9a35522929bdb1b87a896a0ff8a18f19d2`.
- Final keyword baseline: accuracy 0.5900, recall 0.4600, F1 0.5287.
- Final ML result: accuracy 0.9100, precision 0.9241, recall 0.8933, F1 0.9085.
- ML produced 11 false positives and 16 false negatives at threshold 0.6.
- The activation gate failed because ML recall was below 90%.
- The project owner accepted 89.33% recall and manually activated the unchanged threshold-0.6 candidate; metadata records the override.

## Files changed

- Modified: `README.md`, `app/main.py`, `app/utils.py`, `requirements.txt`, `tests/test_api_authorization.py`, and this file.
- Added: `app/requirement_detector.py`.
- Added scripts: generator, preparation, training, and evaluation under `scripts/`.
- Added tests: `tests/test_requirement_detector.py` and `tests/test_requirement_detection_data.py`.
- Added prepared data and review files under `data/requirement_detection/`.
- No database migration, lifecycle change, frontend change, or training-dataset schema change was made.

# Current State

## Verified working

- Full Python suite: 50/50 tests passed.
- Runtime starts with keyword fallback when the candidate is disabled or unavailable.
- Segmentation, fallback, threshold boundaries, ordering, and whole-batch failure behaviour are tested.
- Dataset schema, deduplication, leakage controls, review integrity, and activation gates are tested.
- Training and validation files are balanced and isolated by generation batch.
- `test.jsonl` contains 300 manually accepted, balanced rows and matches its manifest hash.
- Final evaluation outputs exist under ignored `outputs/requirement_detection/evaluation/`.
- ML correctly rejected all 26 hard negatives and achieved 95.24% specificity on modal non-requirements.

## Still incomplete

- The ML candidate is enabled locally by explicit owner override; keyword detection remains its runtime failure fallback.
- The ignored local model artifact must be copied or retrained before another checkout can use ML runtime.
- A future improved candidate needs new development evidence and a new independent final test.

# Known Issues / Technical Debt

- Synthetic Gemini language may differ from real SRS language and create style bias.
- Development labels were validated structurally but were not comprehensively human-reviewed.
- The frozen test has now been used and cannot be used to tune or select a replacement model.
- Classification cannot recover requirements already damaged or merged by extraction.
- Scanned and mixed PDFs still lack page-level rasterisation/OCR.
- MiniLM truncates long inputs; segmentation must continue producing sentence/short-paragraph units.
- Logistic Regression output is a useful confidence score, not a calibrated certainty claim.
- Gemini SDK retries may make one failed manual generation call exceed its configured HTTP timeout.
- Torch reports an extension-version warning in the current environment, although CPU encoding worked.
- RAG remains character-chunked with `k=1`, no score threshold or reranking.
- The model directory is ignored by Git; a fresh checkout needs a copied or retrained artifact.

# Next Priorities

1. Run a real-document CPU/VRAM smoke test with the enabled classifier.
2. Implement page-level hybrid OCR for scanned/mixed PDFs.
3. If improving the classifier later, use new development evidence and a new independent final test.
4. Improve RAG chunking, scored top-k retrieval, and evaluation after OCR.

# Pitfalls / Lessons Learned

- Work from the application checkout at `C:\Users\JUN KIAT\Desktop\FYP`.
- Use `C:\Users\JUN KIAT\anaconda3\envs\FYP\python.exe`.
- Do not edit the `text` column in `test_review.csv`; its hash protects review integrity.
- For relabelled rows, provide a valid corrected label and a category consistent with that label.
- Do not adjust the current threshold/model using the frozen-test results.
- Do not run another activation decision on this same frozen test.
- Do not alter activation metadata without an explicit owner decision; preserve the recorded override.
- Do not load untrusted Joblib artifacts.
- Generator output must remain synthetic; never upload project/user documents to Gemini.
- Existing invalid generation batches must be regenerated, not silently skipped.
- API tests install lightweight AI-module substitutes and must remove them to avoid polluting later tests.
- Do not re-enable Uvicorn reload around Unsloth-generated files.

# Notes for the Next Session

1. Read `AGENTS.md`, this file, and `README.md` first.
2. Review `app/requirement_detector.py` and the four Phase 2A scripts before changing behaviour.
3. Treat `data/requirement_detection/test.jsonl` and its manifest as a spent final test, not development data.
4. Preserve the train/validation/test separation and generation-batch grouping.
5. Preserve the manual-override metadata: the candidate is enabled although its precommitted gate failed.
6. Keep detector confidence/method out of the database and existing API stream.
7. Do not expose lifecycle or export metadata to User history/reporting.
8. Do not change the canonical four-field fine-tuning dataset.
9. Do not trigger automatic fine-tuning.
10. Start the backend from repository root with `python main.py` or the documented package Uvicorn command.
11. Ask before architecture, database-schema, API-contract, or AI-pipeline changes.
12. Update this document at the end of the next coding session.
