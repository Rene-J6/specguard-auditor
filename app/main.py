# =====================================================================
# FORCE EXPANDABLE SEGMENTS TO PREVENT VRAM FRAGMENTATION CRASHES
# =====================================================================
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# =====================================================================
# 1. INITIALIZE PYTORCH FIRST (Secures DLL search paths on Windows)
# =====================================================================
import sys

try:
    import torch
    torch_lib_path = os.path.join(os.path.dirname(torch.__file__), 'lib')
    if os.path.exists(torch_lib_path) and hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(torch_lib_path)
except Exception as e:
    print(f"PyTorch DLL loader notice: {e}")

# =====================================================================
# 2. STANDARD SYSTEM IMPORTS
# =====================================================================
import gc
import re  
import warnings
import shutil
import uuid
from fastapi import FastAPI, File, UploadFile, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from fastapi.responses import StreamingResponse
import json

# Resolve absolute workspace paths
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Custom module imports
from database import (
    init_sqlite_pool, log_audit_to_db, fetch_unvalidated_logs, 
    update_log_status, delete_log_entry, init_auth_db, 
    register_user, verify_login, fetch_user_history,
    get_user_details, update_user_profile,
    fetch_expert_queue, fetch_document_requirements,
    lock_requirement_set, unlock_requirement_set, submit_expert_review,
    fetch_user_notifications, mark_notification_as_read, delete_notification,
    fetch_document_comparison, fetch_expert_audited_logs,
    fetch_all_admin_logs
)
from utils import clean_document_text, extract_text_from_file
from model_engine import load_pipeline_resources

# Initialize databases
init_sqlite_pool()
init_auth_db()

# Initialize FastAPI app
app = FastAPI(title="SpecGuard Core API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = None
tokenizer = None
ocr_engine = None
db = None

@app.on_event("startup")
def startup_event():
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
    role: Optional[str] = "User"
    phone_number: Optional[str] = ""
    company_name: Optional[str] = ""

class ProfileUpdateRequest(BaseModel):
    username: str
    full_name: str
    email: str
    phone_number: Optional[str] = ""
    company_name: Optional[str] = ""
    password: Optional[str] = ""

class AnalysisRequest(BaseModel):
    username: str
    raw_text: str
    document_name: Optional[str] = "Untitled Document"

class LockRequest(BaseModel):
    document_id: str
    expert_username: str

class UnlockRequest(BaseModel):
    document_id: str
    expert_username: str

class SingleRequirementReview(BaseModel):
    id: int
    expert_evaluation: str
    expert_rewrite: str

class SubmitReviewRequest(BaseModel):
    document_id: str
    expert_username: str
    reviews: List[SingleRequirementReview]
    is_approved: bool

# =====================================================================
# ROUTING CONTROLLER ENDPOINTS
# =====================================================================

@app.post("/api/auth/register")
def register(payload: RegisterRequest):
    success, message = register_user(
        payload.username, payload.password, payload.full_name, payload.email, payload.role,
        payload.phone_number, payload.company_name
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}

@app.post("/api/auth/login")
def login(payload: LoginRequest):
    is_valid, role, full_name = verify_login(payload.username, payload.password)
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    
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
    success = update_user_profile(
        payload.username, payload.full_name, payload.email, 
        payload.phone_number, payload.company_name, payload.password
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update profile.")
    return {"message": "Profile updated successfully."}

@app.post("/api/analysis/upload")
async def upload_document(file: UploadFile = File(...)):
    if not ocr_engine:
        raise HTTPException(status_code=503, detail="OCR engine is not loaded.")
    temp_path = os.path.join(TEMP_DIR, file.filename)
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        extracted_raw = extract_text_from_file(temp_path, file.content_type, ocr_engine)
        cleaned = clean_document_text(extracted_raw)
        return {"extracted_text": cleaned}
    except Exception as e:
        import traceback
        print("\n❌ CRITICAL ERROR IN /api/analysis/upload:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/api/analysis/run")
def run_audit(payload: AnalysisRequest):
    global model, tokenizer, db
    if not all([model, tokenizer, db]):
        raise HTTPException(status_code=503, detail="AI engine is not initialized.")

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

    document_id = f"doc_{uuid.uuid4().hex[:8]}"

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

            log_audit_to_db(
                payload.username, current_req, f"{source_filename} | {clause_text}", 
                res, document_id, payload.document_name
            )

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
            yield json.dumps(chunk_data) + "\n"

            del inputs, outputs
            torch.cuda.empty_cache()
            gc.collect()

    return StreamingResponse(analysis_generator(), media_type="text/event-stream")

@app.get("/api/history/{username}")
def get_user_history(username: str):
    df = fetch_user_history(username)
    return df.to_dict(orient="records")

# =====================================================================
# SYSTEM ADMINISTRATIVE CONSOLE ROUTING
# =====================================================================

@app.get("/api/admin/all-logs")
def get_admin_audit_console():
    return fetch_all_admin_logs()

@app.post("/api/admin/logs/{log_id}/validate")
def validate_log(log_id: int, payload: dict):
    update_log_status(log_id, validated_text=payload.get("validated_text", ""), status="Validated")
    return {"message": f"Log {log_id} validated."}

@app.delete("/api/admin/logs/{log_id}")
def purge_log(log_id: int):
    delete_log_entry(log_id)
    return {"message": f"Log {log_id} discarded."}

# =====================================================================
# DOMAIN EXPERT CORE WORKFLOW ROUTING
# =====================================================================

@app.get("/api/expert/queue")
def get_expert_queue_endpoint(expert_username: str):
    return fetch_expert_queue(expert_username)

@app.get("/api/expert/requirements/{document_id}")
def get_document_requirements_endpoint(document_id: str):
    return fetch_document_requirements(document_id)

@app.post("/api/expert/lock")
def lock_document_set_endpoint(payload: LockRequest):
    success = lock_requirement_set(payload.document_id, payload.expert_username)
    if not success:
        raise HTTPException(status_code=409, detail="Document is already claimed by another Expert.")
    return {"message": "Document set successfully locked."}

@app.post("/api/expert/unlock")
def unlock_document_set_endpoint(payload: UnlockRequest):
    success = unlock_requirement_set(payload.document_id, payload.expert_username)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to release the document set lock.")
    return {"message": "Document set successfully returned to the pending pool."}

@app.post("/api/expert/submit")
def submit_review_endpoint(payload: SubmitReviewRequest):
    reviews_data = [r.dict() for r in payload.reviews]
    success = submit_expert_review(payload.document_id, payload.expert_username, reviews_data, payload.is_approved)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process review submission.")
    return {"message": "Review processed successfully."}

@app.get("/api/expert/history/{expert_username}")
def get_expert_history_logs_endpoint(expert_username: str):
    return fetch_expert_audited_logs(expert_username)

# =====================================================================
# USER NOTIFICATIONS & AUDITED COMPARATIVE VIEWS
# =====================================================================

@app.get("/api/notifications/{username}")
def get_notifications_endpoint(username: str):
    return fetch_user_notifications(username)

@app.post("/api/notifications/{notification_id}/read")
def read_notification_endpoint(notification_id: int):
    mark_notification_as_read(notification_id)
    return {"message": "Notification marked as read."}

@app.delete("/api/notifications/{notification_id}")
def remove_notification(notification_id: int):
    delete_notification(notification_id)
    return {"message": "Notification dismissed successfully."}

@app.get("/api/notifications/{username}/compare/{document_id}")
def get_audited_comparison_endpoint(username: str, document_id: str):
    return fetch_document_comparison(document_id, username)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)