import re

import pdfplumber


MIN_EXTRACTABLE_CHARACTERS = 50


class InvalidPdfError(ValueError):
    pass


class NoExtractableTextError(ValueError):
    pass


def clean_document_text(text: str) -> str:
    """Removes structural metadata noise and explicit escape character artifacts."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = re.sub(r"\\", "", text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_text_from_pdf(file_path: str) -> str:
    """Extract selectable text from a digital PDF in page order."""
    try:
        with pdfplumber.open(file_path) as pdf:
            raw_text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        raise InvalidPdfError("Invalid or corrupted PDF.") from exc

    if sum(not character.isspace() for character in raw_text) < MIN_EXTRACTABLE_CHARACTERS:
        raise NoExtractableTextError(
            "Only digital PDFs with extractable text are supported."
        )
    return raw_text
