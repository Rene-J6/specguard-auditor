import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PDFPlumberLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

load_dotenv()

DB_PATH = "data/knowledge_base/chroma_db"
SOURCE_DIR = "data/knowledge_base"

def ingest():
    print("📡 Loading Embedding Model (BGE-M3)...")
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3", model_kwargs={'device': 'cpu'})

    pdf_files = list(Path(SOURCE_DIR).glob("*.pdf"))
    if not pdf_files:
        print("❌ No PDFs found. Place SIRIM documents in data/knowledge_base/")
        return

    docs = []
    for pdf in pdf_files:
        print(f"📖 Reading {pdf.name}...")
        loader = PDFPlumberLoader(str(pdf))
        docs.extend(loader.load())

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_documents(docs)

    print(f"📦 Creating Vector DB with {len(chunks)} chunks...")
    Chroma.from_documents(documents=chunks, embedding=embeddings, persist_directory=DB_PATH)
    print("✅ Knowledge Base Ready!")

if __name__ == "__main__":
    ingest()