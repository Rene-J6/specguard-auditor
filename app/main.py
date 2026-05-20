import os
import gc
import re
import warnings
import json
import sqlite3
import torch
import streamlit as st

# Custom module imports from split architecture layout files
from database import init_sqlite_pool, log_audit_to_db, SQLITE_DB_PATH, EXPORT_JSONL_PATH
from utils import clean_document_text, extract_text_from_file
from model_engine import load_pipeline_resources

# --- SAFETY SETTINGS ---
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
warnings.filterwarnings("ignore")

# Resolve local runtime path targets
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize database mapping pool layout immediately on startup
init_sqlite_pool()

def main():
    try:
        model, tokenizer, ocr_engine, db = load_pipeline_resources()
    except Exception as e:
        st.error(f"Initialization Failure: {e}")
        return

    # Track app memory states safely across individual UI clicks
    if 'raw_text' not in st.session_state: st.session_state['raw_text'] = ""
    if 'reqs' not in st.session_state: st.session_state['reqs'] = []
    if 'audit_results' not in st.session_state: st.session_state['audit_results'] = {}

    user_portal_tab, admin_dashboard_tab = st.tabs(["🔍 User Auditor Portal", "👑 Admin Validation Hub"])

    # =====================================================================
    # ENVIRONMENT A: USER AUDITOR PORTAL
    # =====================================================================
    with user_portal_tab:
        st.title("🛡️ Sovereign XAI-SRA Auditor")
        st.caption("Active Dual-Model Compliance Engine Logging Verification Records to Local Storage")

        st.sidebar.header("📁 Step 1: Ingestion")
        uploaded_file = st.sidebar.file_uploader("Upload Specification Sheet", type=["pdf", "png", "jpg"])
        
        if uploaded_file and st.sidebar.button("🔍 Extract & Clean Text"):
            temp_path = os.path.join(TEMP_DIR, uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            with st.spinner("Parsing text layouts..."):
                extracted_raw = extract_text_from_file(temp_path, uploaded_file.type, ocr_engine)
                st.session_state['raw_text'] = clean_document_text(extracted_raw)
                st.sidebar.success("Payload structured successfully!")

        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("📋 Requirements Isolation Zone")
            st.session_state['raw_text'] = st.text_area("Sanitized Body Specifications Text:", value=st.session_state['raw_text'], height=180)
            
            if st.button("🔎 Identify All Requirements"):
                if st.session_state['raw_text']:
                    sentences = re.split(r'(?<=[.!?]) +', st.session_state['raw_text'])
                    keywords = ["shall", "should", "must", "needs to", "will", "required to"]
                    st.session_state['reqs'] = [s.strip().replace("\n", " ") for s in sentences if any(k in s.lower() for k in keywords) and len(s.strip()) > 15]
                    st.session_state['audit_results'] = {}
                    st.success(f"Isolated {len(st.session_state['reqs'])} commitment targets.")
                else:
                    st.error("Extraction text area is empty.")

            if st.session_state['reqs']:
                st.markdown("---")
                for idx, req in enumerate(st.session_state['reqs']):
                    with st.expander(f"Requirement {idx + 1}", expanded=True):
                        st.write(f"*{req}*")
                        
                        if st.button(f"🚀 Audit Point {idx + 1}", key=f"audit_btn_{idx}"):
                            with st.spinner("Model 1 matching clause indexes..."):
                                docs = db.similarity_search(req, k=1)
                                context = docs[0].page_content if docs else "General Standards Rule Framework"
                                
                            with st.spinner("Model 2 generating tracking metrics..."):
                                pipeline_input = f"Req: {req}\nRule: {context}"
                                prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\nAnalyze this software requirement against the matched framework standard rule.<|eot_id|><|start_header_id|>user<|end_header_id|>\n{pipeline_input}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
                                
                                inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
                                with torch.no_grad():
                                    outputs = model.generate(**inputs, max_new_tokens=400, use_cache=True)
                                
                                res = tokenizer.decode(outputs[0], skip_special_tokens=True).split("assistant\n")[-1].strip()
                                st.session_state['audit_results'][idx] = res
                                
                                # Automatic shadow database capture execution
                                log_audit_to_db(req, context, res)
                                
                                del inputs, outputs
                                torch.cuda.empty_cache()
                                gc.collect()

        with col2:
            st.subheader("⚖️ High-Fidelity Audit Report Output")
            if not st.session_state['audit_results']:
                st.info("Awaiting execution trigger profiles from the active column.")
            for idx in sorted(st.session_state['audit_results'].keys()):
                with st.container(border=True):
                    st.markdown(f"📊 **Audit Block #{idx + 1}**")
                    st.write(st.session_state['audit_results'][idx])

    # =====================================================================
    # ENVIRONMENT B: ADMIN VALIDATION HUB (HUMAN-IN-THE-LOOP)
    # =====================================================================
    with admin_dashboard_tab:
        st.header("👑 Admin Human-in-the-Loop Validation Dashboard")
        
        admin_password = st.text_input("Enter Admin Cryptographic Token", type="password")
        if admin_password == "admin123":
            st.success("Authorization cleared! Accessing the pending model optimization records.")
            
            # FIXED CLEAN STRUCTURE:
            conn = sqlite3.connect(SQLITE_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id, bad_requirement, document_reference, analysis, suggested_rewrite FROM pending_pool WHERE status='Pending'")
            pending_rows = cursor.fetchall()
            conn.close()

            st.write(f"### Current Unvalidated Records: `{len(pending_rows)} items pending`")
            
            if pending_rows:
                st.markdown("---")
            
            for row_id, bad_req, doc_ref, old_analysis, old_rewrite in pending_rows:
                with st.container(border=True):
                    st.markdown(f"#### 📦 Data Asset Tracking ID: #{row_id}")
                    st.text_input(f"Input Verbatim Source [{row_id}]:", value=bad_req, disabled=True, key=f"adm_in_{row_id}")
                    st.text_input(f"Mapped Clause Reference [{row_id}]:", value=doc_ref, disabled=True, key=f"adm_ref_{row_id}")
                    
                    new_analysis = st.text_area(f"Verify Analysis Output [{row_id}]:", value=old_analysis, height=100, key=f"adm_an_{row_id}")
                    new_rewrite = st.text_area(f"Verify Suggested Rewrite [{row_id}]:", value=old_rewrite, height=80, key=f"adm_rw_{row_id}")
                    
                    act_col1, act_col2, _ = st.columns([1, 1, 4])
                    
                    with act_col1:
                        if st.button("✅ Approve Asset", key=f"app_btn_{row_id}"):
                            conn = sqlite3.connect(SQLITE_DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute("UPDATE pending_pool SET analysis=?, suggested_rewrite=?, status='Approved' WHERE id=?", (new_analysis, new_rewrite, row_id))
                            conn.commit()
                            conn.close()
                            st.rerun()
                            
                    with act_col2:
                        if st.button("❌ Reject Asset", key=f"rej_btn_{row_id}"):
                            conn = sqlite3.connect(SQLITE_DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute("UPDATE pending_pool SET status='Rejected' WHERE id=?", (row_id,))
                            conn.commit()
                            conn.close()
                            st.rerun()

            st.markdown("---")
            st.subheader("📦 Training Dataset Compiler Tools")
            if st.button("🚀 Compile and Export Approved Records to dataset.jsonl"):
                conn = sqlite3.connect(SQLITE_DB_PATH)
                cursor = conn.cursor()
                cursor.execute("SELECT bad_requirement, document_reference, analysis, suggested_rewrite FROM pending_pool WHERE status='Approved'")
                approved_rows = cursor.fetchall()
                conn.close()
                
                if not approved_rows:
                    st.warning("Export aborted: No rows have been marked 'Approved' in the log database yet.")
                else:
                    with open(EXPORT_JSONL_PATH, "a", encoding="utf-8") as jsonl_file:
                        for b_req, d_ref, an, sw in approved_rows:
                            data_block = {
                                "bad_requirement": b_req,
                                "document_reference": d_ref,
                                "analysis": an,
                                "suggested_rewrite": sw
                            }
                            jsonl_file.write(json.dumps(data_block) + "\n")
                            
                    conn = sqlite3.connect(SQLITE_DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM pending_pool WHERE status='Approved'")
                    conn.commit()
                    conn.close()
                    
                    st.success(f"Success! Appended {len(approved_rows)} certified ground-truth elements into dataset.jsonl.")
        else:
            if admin_password != "":
                st.error("Invalid token. Verification authentication signature failed.")

if __name__ == "__main__":
    main()