import re
import pdfplumber

def clean_document_text(text: str) -> str:
    """Removes standard structural metadata noise from raw extractions."""
    text = re.sub(r'\\', '', text)  # Wipe tags
    text = re.sub(r'\\', '', text)
    text = re.sub(r'\s+', ' ', text)               # Repair mid-sentence wraps
    return text.strip()

def extract_text_from_file(file_path: str, file_type: str, ocr_engine) -> str:
    """Extracts text layer from digital PDFs or runs OCR fallback for scanned sheets."""
    raw_text = ""
    if file_type == "application/pdf":
        with pdfplumber.open(file_path) as pdf:
            raw_text = " ".join([page.extract_text() or "" for page in pdf.pages])
            
    # Fallback to local PaddleOCR execution if PDF text layer is unreadable/scanned
    if len(raw_text.strip()) < 50:
        result = ocr_engine.ocr(file_path, cls=True)
        raw_text = " ".join([line[1][0] for res in result for line in res])
        
    return raw_text