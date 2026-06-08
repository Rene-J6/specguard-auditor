import re
import pdfplumber

def clean_document_text(text: str) -> str:
    """Removes structural metadata noise and explicit escape character artifacts."""
    # FIX: Clean up literal escape characters (\n, \t, \r) that break sentence splitters
    text = text.replace("\n", " ").replace("\t", " ").replace("\r", " ")
    
    # Remove any stray backslashes or redundant multi-spaces
    text = re.sub(r'\\', '', text)
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_text_from_file(file_path: str, file_type: str, ocr_engine) -> str:
    """Extracts text layer from digital PDFs or runs OCR fallback for scanned sheets/images."""
    raw_text = ""
    
    # Process digital layers if the file format is a PDF document
    if "pdf" in file_type.lower():
        with pdfplumber.open(file_path) as pdf:
            raw_text = " ".join([page.extract_text() or "" for page in pdf.pages])
            
    # FIX: If it's a raw image or a scanned/empty PDF layer, route directly to PaddleOCR
    if "image" in file_type.lower() or len(raw_text.strip()) < 50:
        result = ocr_engine.ocr(file_path, cls=True)
        
        # Guard against completely blank images or unreadable files returning None
        if result and result[0]:
            raw_text = " ".join([line[1][0] for res in result for line in res if res])
        
    return raw_text