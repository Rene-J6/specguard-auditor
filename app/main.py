import os
import gc
import re  
import warnings
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import torch
from fastapi.responses import StreamingResponse
import json

# Resolve absolute workspace paths
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Custom module imports from your existing layout
from database import (
    init_sqlite_pool, log_audit_to_db, fetch_unvalidated_logs, 
    update_log_status, delete_log_entry, init_auth_db, 
    register_user, verify_login, fetch_user_history,
    get_user_details, update_user_profile
)
from utils import clean_document_text, extract_text_from_file
from model_engine import load_pipeline_resources

# Initialize databases
init_sqlite_pool()
init_auth_db()

# Initialize FastAPI app
app = FastAPI(title="SpecGuard Core API", version="1.0.0")

# Enable CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to your specific frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for AI resources
model = None
tokenizer = None
ocr_engine = None
db = None

@app.on_event("startup")
def startup_event():
    """Loads and caches the heavy weights once when the server boots up."""
    global model, tokenizer, ocr_engine, db
    try:
        model, tokenizer, ocr_engine, db = load_pipeline_resources()
        print("SpecGuard Core Engine components loaded successfully.")
    except Exception as e:
        print(f"Error initializing core engine components: {e}")

# =====================================================================
# REQUEST & RESPONSE SCHEMAS
# =====================================================================
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str
    email: str

class ProfileUpdateRequest(BaseModel):
    username: str
    full_name: str
    email: str

class AnalysisRequest(BaseModel):
    username: str
    raw_text: str

class ValidationRequest(BaseModel):
    validated_text: str
    status: str = "Validated"

# =====================================================================
# ENDPOINTS
# =====================================================================

@app.post("/api/auth/register")
def register(payload: RegisterRequest):
    if not all([payload.username, payload.password, payload.full_name, payload.email]):
        raise HTTPException(status_code=400, detail="All fields are required.")
    
    success, message = register_user(
        payload.username, payload.password, payload.full_name, payload.email
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}

@app.post("/api/auth/login")
def login(payload: LoginRequest):
    is_valid, role, full_name = verify_login(payload.username, payload.password)
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")
    
    user_details = get_user_details(payload.username) or {}
    return {
        "username": payload.username,
        "full_name": full_name,
        "role": role,
        "email": user_details.get("email", "")
    }

@app.get("/api/profile/{username}")
def get_profile(username: str):
    details = get_user_details(username)
    if not details:
        raise HTTPException(status_code=404, detail="User not found.")
    return details

@app.put("/api/profile")
def update_profile(payload: ProfileUpdateRequest):
    success = update_user_profile(payload.username, payload.full_name, payload.email)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update profile.")
    return {"message": "Profile updated successfully."}

@app.post("/api/analysis/upload")
async def upload_document(file: UploadFile = File(...)):
    """Saves document temporarily, extracts text layer or runs OCR, and cleans results."""
    if not ocr_engine:
        raise HTTPException(status_code=503, detail="OCR engine is not loaded yet.")

    temp_path = os.path.join(TEMP_DIR, file.filename)
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        extracted_raw = extract_text_from_file(temp_path, file.content_type, ocr_engine)
        cleaned = clean_document_text(extracted_raw)
        return {"extracted_text": cleaned}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/api/analysis/run")
def run_audit(payload: AnalysisRequest):
    """Processes requirements against standard rules, streaming results as they are computed."""
    global model, tokenizer, db
    if not all([model, tokenizer, db]):
        raise HTTPException(status_code=503, detail="AI models or vectors are not initialized yet.")

    sentences = re.split(r'(?<=[.!?]) +', payload.raw_text)
    keywords = ["shall", "should", "must", "needs to", "will", "required to"]
    reqs = [
        s.strip().replace("\n", " ") 
        for s in sentences 
        if any(k in s.lower() for k in keywords) and len(s.strip()) > 15
    ]

    if not reqs:
        def empty_generator():
            yield json.dumps({"type": "empty", "message": "No compliance keywords found."}) + "\n"
        return StreamingResponse(empty_generator(), media_type="text/event-stream")

    def analysis_generator():
        total_reqs = len(reqs)
        for idx, current_req in enumerate(reqs):
            docs = db.similarity_search(current_req, k=1)
            if docs:
                matched_doc = docs[0]
                source_filename = os.path.basename(matched_doc.metadata.get('source', 'Unknown'))
                clause_text = matched_doc.page_content
            else:
                source_filename = "General Standards"
                clause_text = "Standard Requirements Engineering Framework"

            pipeline_input = f"Req: {current_req}\nRule: {clause_text}"
            prompt = (
                f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
                f"Analyze this software requirement against the matched framework standard rule.<|eot_id|>"
                f"<|start_header_id|>user<|end_header_id|>\n{pipeline_input}<|eot_id|>"
                f"<|start_header_id|>assistant<|end_header_id|>\n"
            )

            inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=400, use_cache=True)

            res = tokenizer.decode(outputs[0], skip_special_tokens=True).split("assistant\n")[-1].strip()

            final_analysis = res
            final_rewrite = "No rewrite suggested."
            if "### Suggested Rewrite" in res:
                parts = res.split("### Suggested Rewrite")
                final_analysis = parts[0].replace("### Analysis", "").strip()
                final_rewrite = parts[1].strip()

            # Save record to audit DB
            log_audit_to_db(payload.username, current_req, f"{source_filename} | {clause_text}", res)

            # Package result
            chunk_data = {
                "type": "result",
                "progress": {
                    "current": idx + 1,
                    "total": total_reqs
                },
                "data": {
                    "requirement": current_req,
                    "source_filename": source_filename,
                    "clause_text": clause_text,
                    "analysis": final_analysis,
                    "suggested_rewrite": final_rewrite
                }
            }
            # Stream out as a newline-delimited JSON string
            yield json.dumps(chunk_data) + "\n"

            # Memory clean up
            del inputs, outputs
            torch.cuda.empty_cache()
            gc.collect()

    return StreamingResponse(analysis_generator(), media_type="text/event-stream")

@app.get("/api/history/{username}")
def get_user_history(username: str):
    df = fetch_user_history(username)
    # Convert pandas dataframe into list of dictionaries
    return df.to_dict(orient="records")

@app.get("/api/admin/logs")
def get_logs():
    df = fetch_unvalidated_logs()
    return df.to_dict(orient="records")

@app.post("/api/admin/logs/{log_id}/validate")
def validate_log(log_id: int, payload: ValidationRequest):
    update_log_status(log_id, validated_text=payload.validated_text, status=payload.status)
    return {"message": f"Log {log_id} verified and exported."}

@app.delete("/api/admin/logs/{log_id}")
def purge_log(log_id: int):
    delete_log_entry(log_id)
    return {"message": f"Log {log_id} deleted."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)