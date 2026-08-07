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
import io
import tempfile
import warnings
import shutil
import uuid
from pathlib import Path
from fastapi import Cookie, Depends, FastAPI, File, UploadFile, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json

# Resolve absolute workspace paths
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Custom module imports
if __package__ in {None, ""}:
    from database import (
        init_sqlite_pool, log_audit_to_db, fetch_unvalidated_logs, 
        delete_log_entry, delete_document_entry, init_auth_db,
        register_user, authenticate_user, create_session, revoke_session,
        fetch_user_history, fetch_user_document_report, get_user_by_id,
        update_user_profile_by_id,
        change_user_password, create_user_account, list_managed_users,
        update_managed_user,
        fetch_expert_queue, fetch_document_requirements,
        lock_requirement_set, unlock_requirement_set, submit_expert_review,
        fetch_user_notifications, mark_notification_as_read, delete_notification,
        fetch_notification_comparison, fetch_expert_audited_logs,
        fetch_all_admin_logs
    )
    from api_schemas import (
        AdminCreateUserRequest, AdminUpdateUserRequest, AnalysisRequest,
        ChangePasswordRequest, LockRequest, LoginRequest, ProfileUpdateRequest,
        RegisterRequest, SubmitReviewRequest, UnlockRequest,
    )
    from security import (
        SESSION_COOKIE_NAME, get_current_user, require_admin, require_expert,
        require_user,
    )
    from reporting import build_docx_report
    from utils import (
        InvalidPdfError, NoExtractableTextError, clean_document_text,
        extract_text_from_pdf,
    )
    from model_engine import load_pipeline_resources
    from requirement_detector import (
        RequirementDetector, load_requirement_detector, segment_document,
    )
    from retrieval import retrieve_standard_evidence
else:
    from .database import (
        init_sqlite_pool, log_audit_to_db, fetch_unvalidated_logs, 
        delete_log_entry, delete_document_entry, init_auth_db,
        register_user, authenticate_user, create_session, revoke_session,
        fetch_user_history, fetch_user_document_report, get_user_by_id,
        update_user_profile_by_id,
        change_user_password, create_user_account, list_managed_users,
        update_managed_user,
        fetch_expert_queue, fetch_document_requirements,
        lock_requirement_set, unlock_requirement_set, submit_expert_review,
        fetch_user_notifications, mark_notification_as_read, delete_notification,
        fetch_notification_comparison, fetch_expert_audited_logs,
        fetch_all_admin_logs
    )
    from .api_schemas import (
        AdminCreateUserRequest, AdminUpdateUserRequest, AnalysisRequest,
        ChangePasswordRequest, LockRequest, LoginRequest, ProfileUpdateRequest,
        RegisterRequest, SubmitReviewRequest, UnlockRequest,
    )
    from .security import (
        SESSION_COOKIE_NAME, get_current_user, require_admin, require_expert,
        require_user,
    )
    from .reporting import build_docx_report
    from .utils import (
        InvalidPdfError, NoExtractableTextError, clean_document_text,
        extract_text_from_pdf,
    )
    from .model_engine import load_pipeline_resources
    from .requirement_detector import (
        RequirementDetector, load_requirement_detector, segment_document,
    )
    from .retrieval import retrieve_standard_evidence

# Initialize databases
init_sqlite_pool()
init_auth_db()

# Initialize FastAPI app
app = FastAPI(title="SpecGuard Core API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = None
tokenizer = None
db = None
requirement_detector = RequirementDetector()

@app.on_event("startup")
def startup_event():
    global model, tokenizer, db, requirement_detector
    try:
        model, tokenizer, db = load_pipeline_resources()
        print("SpecGuard Core Engine components loaded successfully.")
    except Exception as e:
        print(f"Error initializing core engine components: {e}")
        model = tokenizer = db = None
    requirement_detector = load_requirement_detector()

# =====================================================================
# ROUTING CONTROLLER ENDPOINTS
# =====================================================================


def _public_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "phone_number": user.get("phone_number", ""),
        "company_name": user.get("company_name", ""),
    }


def _set_session_cookie(response, token):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=12 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )

@app.post("/api/auth/register")
def register(payload: RegisterRequest):
    success, message = register_user(
        payload.username, payload.password, payload.full_name, payload.email,
        payload.phone_number, payload.company_name
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}

@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled.")
    token = create_session(user["id"])
    _set_session_cookie(response, token)
    return _public_user(user)


@app.get("/api/auth/me")
def auth_me(current_user=Depends(get_current_user)):
    return _public_user(current_user)


@app.post("/api/auth/logout")
def logout(
    response: Response,
    specguard_session: str | None = Cookie(
        default=None, alias=SESSION_COOKIE_NAME
    ),
):
    revoke_session(specguard_session)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")
    return {"message": "Logged out."}


@app.get("/api/profile")
def get_profile(current_user=Depends(get_current_user)):
    return _public_user(current_user)

@app.put("/api/profile")
def update_profile(
    payload: ProfileUpdateRequest,
    current_user=Depends(get_current_user),
):
    result = update_user_profile_by_id(
        current_user["id"], payload.full_name, payload.email,
        payload.phone_number, payload.company_name,
    )
    if not result["success"]:
        status_code = 409 if result.get("code") == "DUPLICATE_EMAIL" else 400
        raise HTTPException(status_code=status_code, detail=result)
    return _public_user(get_user_by_id(current_user["id"]))


@app.post("/api/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    current_user=Depends(get_current_user),
):
    result = change_user_password(
        current_user["id"], payload.current_password, payload.new_password
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")
    return {"message": "Password changed. Please log in again."}


@app.get("/api/profile/{username}")
def legacy_profile(username: str, current_user=Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="Use /api/profile.")

@app.post("/api/analysis/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user=Depends(require_user),
):
    if Path(file.filename or "").suffix.casefold() != ".pdf" or file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only digital PDF files are supported.")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=TEMP_DIR, suffix=".pdf"
        ) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name

        with open(temp_path, "rb") as uploaded_pdf:
            if uploaded_pdf.read(5) != b"%PDF-":
                raise HTTPException(
                    status_code=415,
                    detail="Only digital PDF files are supported.",
                )

        extracted_raw = extract_text_from_pdf(temp_path)
        cleaned = clean_document_text(extracted_raw)
        return {"extracted_text": cleaned}
    except HTTPException:
        raise
    except InvalidPdfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NoExtractableTextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Text extraction failed.") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/api/analysis/run")
def run_audit(payload: AnalysisRequest, current_user=Depends(require_user)):
    global model, tokenizer, db
    if not all([model, tokenizer, db]):
        raise HTTPException(status_code=503, detail="AI engine is not initialized.")

    predictions = requirement_detector.predict_many(segment_document(payload.raw_text))
    reqs = [item["text"] for item in predictions if item["is_requirement"]]

    if not reqs:
        def empty_generator():
            yield json.dumps({"type": "empty", "message": "No requirements detected."}) + "\n"
        return StreamingResponse(empty_generator(), media_type="text/event-stream")

    document_id = f"doc_{uuid.uuid4().hex[:8]}"

    def analysis_generator():
        total_reqs = len(reqs)
        for idx, current_req in enumerate(reqs):
            retrieval = retrieve_standard_evidence(db, current_req, k=5)
            matched_clause = retrieval["selected_clause"]
            if not matched_clause:
                source_filename = "No relevant standard"
                clause_text = "No relevant standard clause was found."
                final_analysis = clause_text
                final_rewrite = "No rewrite suggested."
                log_audit_to_db(
                    current_user["username"], current_req,
                    f"{source_filename} | {clause_text}", final_analysis,
                    document_id, payload.document_name,
                )
                yield json.dumps({
                    "type": "result",
                    "progress": {"current": idx + 1, "total": total_reqs},
                    "data": {
                        "requirement": current_req,
                        "source_filename": source_filename,
                        "clause_text": clause_text,
                        "analysis": final_analysis,
                        "suggested_rewrite": final_rewrite,
                    },
                }) + "\n"
                continue

            source_filename = matched_clause["source"]
            clause_text = matched_clause["text"]

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
                current_user["username"], current_req, f"{source_filename} | {clause_text}",
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

@app.get("/api/history")
def get_user_history(current_user=Depends(require_user)):
    df = fetch_user_history(current_user["username"])
    return df.to_dict(orient="records")


@app.get("/api/reports/documents/{document_id}/docx")
def export_document_report(
    document_id: str, current_user=Depends(require_user)
):
    report = fetch_user_document_report(document_id, current_user["username"])
    if not report:
        raise HTTPException(status_code=404, detail="Document not found.")
    content, filename = build_docx_report(report)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/history/{username}")
def legacy_user_history(username: str, current_user=Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="Use /api/history.")

# =====================================================================
# SYSTEM ADMINISTRATIVE CONSOLE ROUTING
# =====================================================================

@app.get("/api/admin/all-logs")
def get_admin_audit_console(current_user=Depends(require_admin)):
    return fetch_all_admin_logs()

@app.post("/api/admin/logs/{log_id}/validate")
def validate_log(
    log_id: int, payload: dict, current_user=Depends(require_admin)
):
    raise HTTPException(
        status_code=410,
        detail="Admin validation has been removed. Expert approval is final.",
    )

@app.delete("/api/admin/logs/{log_id}")
def purge_log(log_id: int, current_user=Depends(require_admin)):
    result = delete_log_entry(log_id)
    if not result["success"]:
        status_code = 404 if result.get("code") == "NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=result)
    return {"message": f"Log {log_id} discarded."}

@app.delete("/api/admin/documents/{document_id}")
def purge_document(document_id: str, current_user=Depends(require_admin)):
    result = delete_document_entry(document_id)
    if not result["success"]:
        status_code = 404 if result.get("code") == "NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=result)
    return {"message": f"Document {document_id} discarded.", "deleted": result["deleted"]}


@app.get("/api/admin/users")
def get_admin_users(current_user=Depends(require_admin)):
    return list_managed_users()


@app.post("/api/admin/users")
def create_admin_user(
    payload: AdminCreateUserRequest,
    current_user=Depends(require_admin),
):
    success, message = create_user_account(
        payload.username,
        payload.password,
        payload.full_name,
        payload.email,
        payload.role,
        payload.phone_number,
        payload.company_name,
    )
    if not success:
        status_code = 409 if "exists" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)
    return {"message": message}


@app.patch("/api/admin/users/{user_id}")
def update_admin_user(
    user_id: int,
    payload: AdminUpdateUserRequest,
    response: Response,
    current_user=Depends(require_admin),
):
    changes = payload.model_dump(exclude_unset=True)
    result = update_managed_user(
        actor_user_id=current_user["id"],
        target_user_id=user_id,
        **changes,
    )
    if not result["success"]:
        code = result.get("code")
        status_code = 404 if code == "NOT_FOUND" else 409 if code in {
            "DUPLICATE_EMAIL", "CANNOT_DISABLE_SELF", "LAST_ACTIVE_ADMIN",
            "ACTIVE_EXPERT_LOCK",
        } else 400
        raise HTTPException(status_code=status_code, detail=result)
    if user_id == current_user["id"] and "role" in changes:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")
    return result["user"]

# =====================================================================
# DOMAIN EXPERT CORE WORKFLOW ROUTING
# =====================================================================

@app.get("/api/expert/queue")
def get_expert_queue_endpoint(current_user=Depends(require_expert)):
    return fetch_expert_queue(current_user["username"])

@app.get("/api/expert/requirements/{document_id}")
def get_document_requirements_endpoint(
    document_id: str, current_user=Depends(require_expert)
):
    result = fetch_document_requirements(document_id, current_user["username"])
    if not result["success"]:
        status_code = 404 if result["code"] == "NOT_FOUND" else 403
        raise HTTPException(status_code=status_code, detail=result["code"])
    return result["requirements"]

@app.post("/api/expert/lock")
def lock_document_set_endpoint(
    payload: LockRequest, current_user=Depends(require_expert)
):
    result = lock_requirement_set(payload.document_id, current_user["username"])
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result)
    return {"message": "Document set successfully locked.", **result}

@app.post("/api/expert/unlock")
def unlock_document_set_endpoint(
    payload: UnlockRequest, current_user=Depends(require_expert)
):
    result = unlock_requirement_set(payload.document_id, current_user["username"])
    if not result["success"]:
        raise HTTPException(status_code=400, detail="Failed to release the document set lock.")
    return {"message": "Document set successfully returned to the pending pool."}

@app.post("/api/expert/submit")
def submit_review_endpoint(
    payload: SubmitReviewRequest, current_user=Depends(require_expert)
):
    reviews_data = [r.model_dump() for r in payload.reviews]
    result = submit_expert_review(
        payload.document_id,
        current_user["username"],
        reviews_data,
        payload.is_approved,
    )
    if not result["success"]:
        status_code = 409 if result.get("code") in {
            "NOT_LOCK_OWNER", "REVIEW_SET_MISMATCH"
        } else 500
        raise HTTPException(status_code=status_code, detail=result)
    return {"message": "Review processed successfully.", **result}

@app.get("/api/expert/history")
def get_expert_history_logs_endpoint(current_user=Depends(require_expert)):
    return fetch_expert_audited_logs(current_user["username"])


@app.get("/api/expert/history/{expert_username}")
def legacy_expert_history(
    expert_username: str, current_user=Depends(get_current_user)
):
    raise HTTPException(status_code=410, detail="Use /api/expert/history.")

# =====================================================================
# USER NOTIFICATIONS & AUDITED COMPARATIVE VIEWS
# =====================================================================

@app.get("/api/notifications")
def get_notifications_endpoint(current_user=Depends(require_user)):
    return fetch_user_notifications(current_user["username"])

@app.post("/api/notifications/{notification_id}/read")
def read_notification_endpoint(
    notification_id: int, current_user=Depends(require_user)
):
    if not mark_notification_as_read(notification_id, current_user["username"]):
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"message": "Notification marked as read."}

@app.delete("/api/notifications/{notification_id}")
def remove_notification(
    notification_id: int, current_user=Depends(require_user)
):
    if not delete_notification(notification_id, current_user["username"]):
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"message": "Notification dismissed successfully."}

@app.get("/api/notifications/{notification_id}/comparison")
def get_audited_comparison_endpoint(
    notification_id: int, current_user=Depends(require_user)
):
    comparison = fetch_notification_comparison(
        notification_id, current_user["username"]
    )
    if comparison is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return comparison


@app.get("/api/notifications/{username}")
def legacy_notifications(username: str, current_user=Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="Use /api/notifications.")


@app.get("/api/notifications/{username}/compare/{document_id}")
def legacy_notification_comparison(
    username: str, document_id: str, current_user=Depends(get_current_user)
):
    raise HTTPException(
        status_code=410,
        detail="Use /api/notifications/{notification_id}/comparison.",
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
