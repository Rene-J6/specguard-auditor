# Project Status

- **Last updated:** 2026-08-05
- **Current branch:** `main` at `8129330 Database lifecycle improvement`
- **Overall status:** In Progress
- **Current development goal:** Stabilize the local audit platform after the lifecycle and authentication refactors.
- **Next immediate task:** Implement real page-level OCR for scanned and mixed PDFs.
- **Working tree:** Authentication, Admin User Management, and DOCX report work is implemented but uncommitted.
- **Preserve:** `AGENTS.md` contains a separate user-owned uncommitted edit.

# Project Overview

SpecGuard is a local-first platform for auditing English Software Requirements Specification documents.

It extracts requirements from uploaded PDFs or images, retrieves local standards, explains quality problems, suggests rewrites, supports Expert review, and prepares verified examples for manual fine-tuning.

Current scope:

- English PDF and image documents.
- Local Windows deployment on an RTX 4060 Laptop GPU with 8 GB VRAM.
- React/Vite/Tailwind frontend and FastAPI backend.
- SQLite auth/audit storage and a persisted Chroma knowledge base.
- Local inference, human review, and manually initiated fine-tuning only.

# Current Architecture

## Main components

- Frontend: React 19, Vite, and Tailwind in `frontend/`.
- Backend API: FastAPI routes in `app/main.py`.
- Auth/API schemas: `app/security.py` and `app/api_schemas.py`.
- Data logic: `app/database.py`.
- DOCX generation: `app/reporting.py` using `python-docx`.
- Storage: `storage/auth.db` and `storage/training_pool.db`.
- Retrieval: Chroma with `BAAI/bge-m3` embeddings on CPU.
- OCR/LLM: pdfplumber, OpenCV, EasyOCR, and 4-bit Llama-3-8B with an Unsloth LoRA adapter.

## AI pipeline

```text
Upload
  → PDF extraction / image OCR
  → text cleaning
  → modal-keyword requirement detection
  → Chroma similarity retrieval
  → local LLM analysis and rewrite
  → Expert review
  → canonical training dataset
  → manual fine-tuning
```

## Authentication and roles

- Login creates a 12-hour random server-side session.
- The browser receives an HttpOnly `specguard_session` cookie.
- SQLite stores only the SHA-256 token hash.
- API authorization derives identity and role from the session, never request usernames.
- Public registration always creates a User.
- Admin may directly create or promote User, Expert, and Admin accounts.
- Password hashing intentionally remains `PBKDF2-SHA256:10000`.
- Usernames are immutable because audit ownership is stored by username across databases.
- User: upload, audit, history, notifications, comparisons, and DOCX reports.
- Expert: queue, one active lock, release, approve/reject, and Expert history.
- Admin: user management, lifecycle monitoring, and audit deletion; no content approval.

## Stable design decisions

- Lifecycle remains `PENDING → LOCKED → APPROVED | REJECTED`.
- One active document lock per Expert.
- An Expert with an active lock cannot be disabled or moved to another role.
- User history/report never exposes lifecycle, assigned Expert, or training-export metadata.
- Canonical training fields remain `bad_requirement`, `document_reference`, `analysis`, `suggested_rewrite`.
- Never append legacy `instruction` / `output` records.
- Never trigger fine-tuning automatically.
- Never introduce cloud retrieval/inference without explicit approval.

# Completed in This Session

## Authentication database

- Added versioned auth migration v1 and `auth_schema_migrations`.
- Backed up the original database to `storage/auth.pre_session_auth_v1.backup.db`.
- Added `is_active`, `created_at`, `updated_at`, and `last_login_at` to users.
- Added case-insensitive username/email uniqueness.
- Added hashed, expiring SQLite sessions.
- Migrated the real database with all three existing accounts preserved and active.
- Kept the existing PBKDF2 algorithm and 10,000 iteration setting by explicit decision.
- Added first-Admin CLI at `scripts/create_admin.py`.

## Authorization and account management

- Replaced caller-provided identity with session-derived identity.
- Added `/api/auth/me`, logout, and current-password change endpoints.
- Fixed email login to return the canonical username.
- Restricted public registration to User accounts.
- Added Admin list/create/update user APIs.
- Added self-disable, last-active-Admin, and active-Expert-lock guards.
- Role/status changes revoke target-user sessions.
- Notification read/delete/comparison now enforce User ownership.
- Restricted CORS to local Vite origins with credentials.

## Frontend and report export

- Added session restoration after browser refresh and cookie-aware requests.
- Removed public registration role selection.
- Removed all frontend identity fields from User/Expert workflow requests.
- Added Admin User Management search, role/status filters, create/edit, enable/disable, and activity statistics.
- Added current-password verification and logout after password change.
- Added owner-scoped DOCX export from User History.
- DOCX contains summary statistics, standards distribution, AI findings, and eligible Expert content.
- DOCX excludes lifecycle, assigned Expert, dataset, and export metadata.

## Files changed

- Backend/docs: `README.md`, `app/api_schemas.py`, `app/database.py`, `app/main.py`, `app/reporting.py`, `app/security.py`, and `HANDOFF.md`.
- Frontend/CLI: `frontend/src/App.jsx` and `scripts/create_admin.py`.
- Tests: `tests/test_api_authorization.py`, `tests/test_authentication.py`, and `tests/test_report_export.py`.

# Current State

## Verified working

- Full Python suite: 24 tests passed.
- Authentication/database tests: 12 passed.
- API authorization tests: 3 passed.
- DOCX report tests: 3 passed.
- Existing lifecycle tests: 5 passed.
- Frontend ESLint passed.
- Frontend production build passed.
- Real `app.main` package import completed in about 63 seconds.
- Auth schema version is 1; three existing accounts remain active.
- Lifecycle schema remains version 2.
- Root launcher still uses Uvicorn with reload disabled.

## Still incomplete

- Scanned PDFs are not rasterized page-by-page, so PDF OCR is not functional.
- Mixed PDFs do not reliably OCR image-only pages.
- Requirement detection remains modal-keyword substring matching.
- RAG remains character-chunked with `k=1`, no threshold or reranking.
- Audit Report Export currently supports DOCX only, not PDF.
- Frontend API base URL remains hardcoded.

# Known Issues / Technical Debt

- PDF OCR fallback passes a PDF path into image OCR instead of rendered page images.
- Knowledge-base ingestion has no OCR fallback.
- Upload filenames/types/sizes are not safely validated.
- PBKDF2-SHA256 at 10,000 iterations is intentionally retained but remains a security weakness outside this local FYP scope.
- There is no forgot-password or Admin password-reset workflow.
- Local HTTP cookies use `Secure=False`; change this if HTTPS is introduced.
- SameSite=Lax and local-origin CORS are used without a separate CSRF token.
- `app/main.py` imports Torch/Unsloth at package import and remains slow.
- Frontend `App.jsx` remains monolithic and the API URL is hardcoded.
- Training dependencies remain unpinned/inconsistent; EasyOCR and datasets are not explicit requirements.
- LLM and OCR share 8 GB VRAM without explicit budgeting.
- Saved model files are an adapter, not a self-contained base model.
- SQLite and JSONL cannot form one atomic transaction; `training_exports` remains the reconciliation mechanism.
- Do not re-enable Uvicorn reload around Unsloth-generated files.

# Next Priorities

1. Implement page-level hybrid OCR for scanned/mixed PDFs and reuse it in RAG ingestion.
2. Add digital, scanned, and mixed-PDF fixtures and extraction tests.
3. Add upload filename, type, and size validation.
4. Replace requirement substring matching with boundary-aware detection and an evaluation set.
5. Improve RAG chunking, deterministic re-ingestion, scored top-k retrieval, and evaluation.
6. Pin and clean the RTX 4060 dependency matrix and add VRAM/startup smoke tests.
7. Add PDF report export only if required after DOCX validation.
8. Split the frontend monolith and move API configuration to environment settings.

# Pitfalls / Lessons Learned

- The application checkout is `C:\Users\JUN KIAT\Desktop\FYP`, not the Documents directory.
- Use `C:\Users\JUN KIAT\anaconda3\envs\FYP\python.exe`.
- Start the backend from repository root with `python main.py`.
- Use `npm.cmd`, not `npm`, when PowerShell script execution is disabled.
- Back up `auth.db` before changing auth schema; the v1 backup already exists.
- Do not edit usernames after account creation; cross-database ownership depends on them.
- Do not disable/demote an Expert while that Expert owns a lock.
- Do not add Admin account deletion or password reset without a new approved plan.
- Keep User report/history metadata separated from internal lifecycle state.
- Full real package import can take over one minute; lightweight API tests stub only the AI engine import.

# Notes for the Next Session

1. Read `AGENTS.md`, this file, and `README.md` first.
2. Preserve the existing user-owned `AGENTS.md` edit.
3. Review `app/utils.py`, `app/main.py`, and `scripts/ingest_rag.py` first for OCR work.
4. Add failing OCR/extraction tests before changing extraction behavior.
5. Reuse one page-level extraction implementation for uploads and knowledge-base ingestion.
6. Do not rerun auth or lifecycle migrations without checking backups and schema versions.
7. Do not expose session tokens to JavaScript or store them in localStorage.
8. Do not restore caller-provided username authorization fallbacks.
9. Do not expose lifecycle/export metadata to User history or reports.
10. Keep manual fine-tuning and the canonical four-field dataset unchanged.
11. Ask before architecture, database-schema, API-contract, or AI-pipeline changes.
12. Rewrite this file at the end of each completed coding session.
