import pdfplumber
import cv2
import numpy as np
import re

def clean_document_text(text: str) -> str:
    """Removes structural metadata noise and explicit escape character artifacts."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = re.sub(r'\\', '', text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def extract_text_from_file(file_path: str, file_type: str, ocr_engine) -> str:
    """Extracts text from digital PDFs or runs an advanced contrast-enhanced and upscaled OCR for handwriting."""
    raw_text = ""
    
    # 1. Process digital layers for PDF documents
    if "pdf" in file_type.lower():
        try:
            with pdfplumber.open(file_path) as pdf:
                raw_text = " ".join([page.extract_text() or "" for page in pdf.pages])
        except Exception as pdf_err:
            print(f"Digital PDF extraction notice: {pdf_err}")
            
    # 2. Process via EasyOCR if it is an image or if the digital PDF text layer is empty
    if "image" in file_type.lower() or len(raw_text.strip()) < 50:
        processed_input = file_path # Fallback to file path
        
        try:
            img = cv2.imread(file_path)
            if img is not None:
                # A. UPSCALE: Double the size using cubic interpolation to make handwriting distinct
                h, w = img.shape[:2]
                upscaled = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
                
                # B. GRAYSCALE: Convert upscaled image to grayscale
                gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
                
                # C. CONTRAST: Apply CLAHE to sharpen ink outlines against paper background
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                processed_input = clahe.apply(gray)
        except Exception as prep_err:
            print(f"OpenCV handwriting preprocessing failed: {prep_err}. Using raw file.")

        try:
            # D. PARAGRAPH CLUSTERING: Group individual words into coherent sentences
            # paragraph=True forces EasyOCR to merge adjacent boxes horizontally to maintain reading order
            results = ocr_engine.readtext(processed_input, paragraph=True)
            if results:
                # When paragraph=True, results are structured as [ [box_coords, "merged paragraph text"], ... ]
                lines = [str(line[1]) for line in results if line and len(line) > 1]
                raw_text = "\n\n".join(lines)
        except Exception as ocr_err:
            print(f"EasyOCR text extraction failed: {ocr_err}")
        
    return raw_text
