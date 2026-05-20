# 🛡️ SpecGuard: Sovereign Explainable AI Software Requirements Auditor

**SpecGuard** is an automated, high-fidelity compliance assurance pipeline designed to audit software engineering requirements against international and national standards (including **ISO/IEC/IEEE 29148, ISO/IEC 25010, ISO 9001**, and local frameworks like **MyDIGITAL** and **Industry4WRD**).

Built as a completely **sovereign, local-first AI system**, SpecGuard processes enterprise software specification sheets fully offline—ensuring total data privacy while eliminating reliance on expensive public cloud APIs.

---

## 🔄 System Architecture & Data Flow

SpecGuard features a **Split-Responsibility Dual-Model Architecture** optimized to operate efficiently on consumer-grade hardware (tested on an 8GB VRAM GPU).

1. **Phase 1: Ingestion & Parsing:** Extracts raw document layers using digital PDF vector tracking or falls back to CPU-bound optical character recognition layout parsing.
2. **Phase 2: Deterministic Isolation:** Isolates commitment language strings via rule-based keyword matching to mitigate early model hallucination.
3. **Phase 3: Model 1 Routing (CPU):** A localized vector space model maps sentences semantically to strict rule indexes inside a vector database.
4. **Phase 4: Model 2 Generation (GPU):** A fine-tuned local quantized LLM interprets the combined requirement-rule context, outputting an explicit audit matrix breaking down violations and producing professional re-writes.

---

## 🛠️ The Tech Stack

- **Frontend UI Dashboard:** Streamlit
- **LLM Acceleration Framework:** Unsloth (PEFT/LoRA 4-bit Quantization)
- **Deep Learning Architecture Base:** PyTorch & Hugging Face Transformers
- **RAG Orchestration & Embeddings:** LangChain Framework
- **Vector Database Vector Space:** ChromaDB (`BAAI/bge-m3` multi-lingual mapping engine)
- **Layout OCR Processing:** PaddleOCR (Forced on CPU)
- **Shadow Log Storage Pool:** SQLite Database (Human-in-the-Loop Data Flywheel)

---

## 📂 Repository Organization

```text
├── app/
│   ├── main.py          # UI Interface layout coordinator
│   ├── model_engine.py  # Model initializers and execution routing
│   ├── database.py      # SQLite data storage transactions
│   └── utils.py         # Text cleaners and extraction parsers
├── data/
│   ├── training/        # Appended training records (dataset.jsonl)
│   └── temp/            # Local scratch area for temporary uploads
├── models/              # Destination directory for fine-tuned adapters
├── scripts/             # Local fine-tuning and standalone ingestion scripts
└── requirements.txt     # Complete environment dependencies layout