import json
import logging
import re
from pathlib import Path


KEYWORDS = ("shall", "should", "must", "needs to", "will", "required to")
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "requirement_detector"
_LIST_ITEM = re.compile(r"^\s*(?:[-*\u2022]\s+|\(?\d+[.)]\s+)")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'\-*\u2022])")
_ENDS_SENTENCE = re.compile(r"[.!?][\"')\]]?$")
LOGGER = logging.getLogger(__name__)


def has_modal_keyword(text):
    lowered = text.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


def keyword_is_requirement(text):
    return len(text.strip()) > 15 and has_modal_keyword(text)


def keyword_predictions(texts):
    return [
        {
            "text": text,
            "is_requirement": keyword_is_requirement(text),
            "confidence": None,
            "method": "keyword_fallback",
        }
        for text in texts
    ]


def _split_block(block):
    marker = _LIST_ITEM.match(block)
    prefix = marker.group(0) if marker else ""
    body = block[len(prefix):] if marker else block
    parts = [part.strip() for part in _SENTENCE_BOUNDARY.split(body) if part.strip()]
    if prefix and parts:
        parts[0] = prefix + parts[0]
    return parts


def segment_document(text):
    """Split text into ordered sentence/paragraph units without rewriting words."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    current = []

    def flush():
        if current:
            blocks.append(" ".join(current))
            current.clear()

    for raw_line in normalized.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            flush()
            continue
        if _LIST_ITEM.match(line):
            flush()
        elif current and _ENDS_SENTENCE.search(current[-1]):
            flush()
        current.append(line)
    flush()

    return [segment for block in blocks for segment in _split_block(block)]


class RequirementDetector:
    def __init__(self, encoder=None, classifier=None, threshold=0.5):
        self.encoder = encoder
        self.classifier = classifier
        self.threshold = float(threshold)

    @property
    def uses_ml(self):
        return self.encoder is not None and self.classifier is not None

    def predict_many(self, texts):
        texts = list(texts)
        if not self.uses_ml:
            return keyword_predictions(texts)
        try:
            embeddings = self.encoder.encode(
                texts,
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            classes = list(self.classifier.classes_)
            requirement_index = classes.index(1)
            probabilities = self.classifier.predict_proba(embeddings)
            return [
                {
                    "text": text,
                    "is_requirement": float(row[requirement_index]) >= self.threshold,
                    "confidence": float(row[requirement_index]),
                    "method": "ml_classifier",
                }
                for text, row in zip(texts, probabilities)
            ]
        except Exception as error:
            LOGGER.warning(
                "Requirement ML inference failed; using keyword fallback: %s", error
            )
            return keyword_predictions(texts)


def load_requirement_detector(model_dir=MODEL_DIR):
    model_dir = Path(model_dir)
    try:
        metadata = json.loads(
            (model_dir / "metadata.json").read_text(encoding="utf-8")
        )
        if not metadata.get("enabled"):
            raise ValueError("artifact is not enabled")

        import joblib
        from sentence_transformers import SentenceTransformer

        encoder = SentenceTransformer(
            str(model_dir / "embedding_model"),
            device="cpu",
            local_files_only=True,
        )
        classifier = joblib.load(model_dir / "classifier.joblib")
        detector = RequirementDetector(
            encoder=encoder,
            classifier=classifier,
            threshold=metadata["threshold"],
        )
        LOGGER.info("Requirement detector loaded with ML classifier.")
        return detector
    except Exception as error:
        LOGGER.warning(
            "Requirement detector unavailable; using keyword fallback: %s", error
        )
        return RequirementDetector()
