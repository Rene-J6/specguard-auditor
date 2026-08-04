# 🛡️ SpecGuard: Local AI Requirements Audit Platform

SpecGuard is a sovereign, local-first compliance auditing platform for software requirements documents. It combines OCR-based document ingestion, semantic rule retrieval, and a fine-tuned local LLM to analyze, audit, and improve requirements against standards such as:

- ISO/IEC/IEEE 29148
- ISO/IEC 25010
- ISO 9001
- Industry4WRD
- MyDIGITAL

The system is designed for offline operation with private data, using local SQLite storage and fine-tuned models on consumer hardware.

---

## 🚀 What This Project Does

- Accepts uploaded specification documents via a web UI
- Extracts text from PDFs and images using OCR
- Identifies requirement statements using compliance-related keywords
- Retrieves related standard clauses from a local Chroma vector store
- Generates natural-language analysis and rewrite suggestions using a fine-tuned local LLM
- Logs audit results for user history, expert review, and admin lifecycle management
- Supports three roles: `User`, `Expert`, and `Admin`

---

## 🧠 Architecture Overview

### Backend

Implemented in `app/` using FastAPI:

- `app/main.py` — REST endpoints for auth, document upload, audit execution, expert workflows, notifications, and admin log management
- `app/model_engine.py` — Loads the fine-tuned LoRA model, embedding model, EasyOCR reader, and Chroma retrieval store
- `app/database.py` — SQLite schema initialization, auth management, audit logging, expert review flows, notification records, and dataset export support
- `app/utils.py` — Text cleaning and PDF/image extraction helpers

### Frontend

Implemented in `frontend/` using React + Vite + Tailwind CSS:

- `frontend/src/App.jsx` — Main application UI with login/register flow, upload and analysis workspace, history viewer, expert queue/editor, notifications, and admin console
- `frontend/package.json` — Frontend dependencies and scripts

### Models & Knowledge Base

- `models/finetuned/sirim_specialist_lora/` — Local fine-tuned LoRA adapter weights and tokenizer
- `data/knowledge_base/chroma_db/` — Persisted Chroma DB for semantic retrieval
- `data/training/dataset.jsonl` — Training dataset collected from expert validation and synthetic generation

---

## 📦 Dependencies

### Python backend

Dependencies are declared in `requirements.txt`. Key packages include:

- `fastapi`, `uvicorn`
- `pydantic`, `python-multipart`
- `easyocr`, `opencv-python`, `pdfplumber`, `python-docx`
- `langchain-huggingface`, `langchain-chroma`, `langchain-community`
- `sentence-transformers`, `chromadb`
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

### 5. Start the backend API

```bash
python app/main.py
```

Or with Uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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
2. Upload a PDF/image spec file for text extraction
3. Run the compliance audit
4. Review results and history

### Domain expert

1. Log in as an `Expert`
2. Claim one pending document set from the expert queue
3. Edit AI evaluations and rewrites
4. Approve submissions to export verified four-field dataset lines, reject them while retaining an audit record, or release the active document

An expert can hold only one active document lock. Documents locked by another expert are not available for review.

### Admin

1. Log in as an `Admin`
2. Monitor records grouped as `PENDING`, `LOCKED`, `APPROVED`, or `REJECTED`
3. Delete individual requirements or complete documents
4. When deleting approved data, remove its corresponding exported training record

Admins do not approve requirement content; expert approval is final. Internal lifecycle and export states are not exposed in standard user history.

---

## 🗂️ File Structure

```text
FYP/
├── app/
│   ├── database.py
│   ├── main.py
│   ├── model_engine.py
│   └── utils.py
├── data/
│   ├── knowledge_base/
│   │   └── chroma_db/
│   ├── logs/
│   ├── temp/
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
