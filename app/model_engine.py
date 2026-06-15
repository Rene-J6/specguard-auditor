import os
import gc
import sys

# 🩹 MONKEY-PATCH: Fix NumPy 2.0 compatibility for the unmaintained 'imgaug' library
try:
    import numpy as np
    if not hasattr(np, "sctypes"):
        # Recreate the deleted sctypes mapping so older packages can resolve their scalar types
        np.sctypes = {
            "int": [np.int8, np.int16, np.int32, np.int64, int],
            "uint": [np.uint8, np.uint16, np.uint32, np.uint64, np.uint],
            "float": [np.float16, np.float32, np.float64, np.longdouble],
        }
except Exception as e:
    print(f"NumPy 2.0 monkey-patch notice: {e}")

# Standard Imports
import torch
from unsloth import FastLanguageModel
from paddleocr import PaddleOCR
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Resolve absolute paths
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
DB_DIR = os.path.join(PROJECT_ROOT, "data", "knowledge_base", "chroma_db")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "finetuned", "sirim_specialist_lora")

def load_pipeline_resources():
    """Loads models while maintaining CPU/GPU hardware isolation."""
    torch.cuda.empty_cache()
    gc.collect()
    
    if not os.path.exists(MODEL_DIR):
        raise FileNotFoundError(f"Missing fine-tuned adapter weights directory at: {MODEL_DIR}")
        
    # Ensure the Chroma vector space directory structure exists to prevent initialization exceptions
    os.makedirs(DB_DIR, exist_ok=True)
        
    # 🤖 MODEL 2: Fine-Tuned Local Llama Adapter (GPU Isolated)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_DIR,
        load_in_4bit=True,
        max_seq_length=1024,
        device_map={"": 0}
    )
    FastLanguageModel.for_inference(model)
    
    # Run PaddleOCR on CPU to completely avoid DLL and RTX 4060 VRAM limitations
    ocr_engine = PaddleOCR(use_textline_orientation=True, lang='en')
    
    # 🤖 MODEL 1: Router Embedding Layer (Forced on CPU to save VRAM)
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={'device': 'cpu'}
    )
    
    # Rule Base Index Matcher
    vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
    
    return model, tokenizer, ocr_engine, vectorstore