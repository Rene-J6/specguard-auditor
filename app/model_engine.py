import os
import gc
import torch
import easyocr  # Import EasyOCR instead of PaddleOCR
from unsloth import FastLanguageModel
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
    
    # 📷 MODEL 3: EasyOCR Reader (Natively utilizes your RTX 4060 GPU via PyTorch)
    ocr_engine = easyocr.Reader(['en'], gpu=torch.cuda.is_available())
    
    # 🤖 MODEL 1: Router Embedding Layer (Forced on CPU to save VRAM)
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={'device': 'cpu'}
    )
    
    # Rule Base Index Matcher
    vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
    
    return model, tokenizer, ocr_engine, vectorstore