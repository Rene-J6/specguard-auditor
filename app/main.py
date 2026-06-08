import os
import gc
import re  
import warnings
import json
import sqlite3
import torch
import streamlit as st

# =====================================================================
# PATH RESOLUTIONS & SETTINGS
# =====================================================================
# Safety Settings for local GPU inference
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
warnings.filterwarnings("ignore")

# Resolve absolute workspace paths dynamically
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Custom module imports from split architecture layout files
from database import (
    init_sqlite_pool, log_audit_to_db, fetch_unvalidated_logs, 
    update_log_status, delete_log_entry, init_auth_db, 
    register_user, verify_login, fetch_user_history # Make sure this is added to database.py!
)
from utils import clean_document_text, extract_text_from_file
from model_engine import load_pipeline_resources

# Initialize databases on startup
init_sqlite_pool()
init_auth_db()

# =====================================================================
# HELPER FUNCTIONS
# =====================================================================
def format_scannable_clause(raw_clause: str, max_chars: int = 250) -> str:
    """Cleans up hanging text fragments and limits lengths for UI scannability."""
    cleaned = raw_clause.strip()
    cleaned = re.sub(r'^[a-z\s,.\-\)]+', '', cleaned)
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    if len(cleaned) > max_chars:
        return cleaned[:max_chars].strip() + "..."
    return cleaned

# =====================================================================
# PAGE CONFIGURATION & STATE INITIALIZATION
# =====================================================================
st.set_page_config(page_title="SpecGuard", layout="wide", initial_sidebar_state="collapsed")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "full_name" not in st.session_state:
    st.session_state["full_name"] = ""
if "role" not in st.session_state:
    st.session_state["role"] = None
if 'raw_text' not in st.session_state: 
    st.session_state['raw_text'] = ""
if 'reqs' not in st.session_state: 
    st.session_state['reqs'] = []
if 'audit_results' not in st.session_state: 
    st.session_state['audit_results'] = {}

# =====================================================================
# MODULE 1: AUTHENTICATION MODAL
# =====================================================================
@st.dialog("Welcome to SpecGuard")
def auth_modal():
    tab_login, tab_register = st.tabs(["🔑 Login", "📝 Sign Up"])
    
    with tab_login:
        st.subheader("Account Login")
        log_username = st.text_input("Username or Email", key="login_user")
        log_password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login", use_container_width=True, type="primary"):
            is_valid, role, full_name = verify_login(log_username, log_password)
            if is_valid:
                st.session_state['logged_in'] = True
                st.session_state['role'] = role
                st.session_state['username'] = log_username
                st.session_state['full_name'] = full_name
                st.rerun()
            else:
                st.error("Invalid credentials. Please try again.")

    with tab_register:
        st.subheader("Create an Account")
        reg_fullname = st.text_input("Full Legal Name *")
        reg_email = st.text_input("Department Email Address *")
        reg_username = st.text_input("Desired Username *")
        reg_password = st.text_input("Password *", type="password")
        reg_confirm = st.text_input("Confirm Password *", type="password")
        
        if st.button("Register", use_container_width=True, type="primary"):
            if not all([reg_fullname, reg_email, reg_username, reg_password, reg_confirm]):
                st.error("All fields are required.")
            elif reg_password != reg_confirm:
                st.error("Passwords do not match.")
            else:
                success, message = register_user(reg_username, reg_password, reg_fullname, reg_email)
                if success:
                    st.success("Registration successful! You can now login.")
                else:
                    st.error(message)

# =====================================================================
# MAIN LAYOUT & ROUTING
# =====================================================================
def main():
    # --- HEADER NAVIGATION ---
    header_col1, header_col2 = st.columns([8, 2])
    with header_col1:
        st.title("🛡️ SpecGuard")
    
    with header_col2:
        if not st.session_state["logged_in"]:
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Login", use_container_width=True):
                    auth_modal()
            with col_b:
                if st.button("Sign Up", use_container_width=True):
                    auth_modal()
        else:
            with st.popover(f"👤 {st.session_state['full_name']}"):
                st.write(f"**Role:** {st.session_state['role']}")
                st.divider()
                if st.button("Personal Profile", use_container_width=True):
                    st.info("Profile settings coming soon.")
                if st.button("System Settings", use_container_width=True):
                    st.info("Settings coming soon.")
                if st.button("Logout", type="primary", use_container_width=True):
                    st.session_state.clear()
                    st.rerun()

    st.divider()

    # --- WORKSPACE ROUTING (Protected) ---
    if st.session_state["logged_in"]:
        
        # Load heavy models only after successful login
        try:
            model, tokenizer, ocr_engine, db = load_pipeline_resources()
        except Exception as e:
            st.error(f"Initialization Failure: {e}")
            return

        # RBAC Enforcement for Tabs
        if st.session_state["role"] == "Admin":
            tabs = st.tabs(["🔍 Analysis", "📜 History", "👑 Admin Dashboard"])
            admin_tab = tabs[2]
        else:
            tabs = st.tabs(["🔍 Analysis", "📜 History"])
            admin_tab = None

        # =====================================================================
        # MODULE 2: ANALYSIS TAB (Core Workflow)
        # =====================================================================
        with tabs[0]:
            st.header("Requirement Analysis Workspace")
            
            # Phase 1: Upload
            uploaded_file = st.file_uploader("Upload Specification Documents (.pdf, .png, .jpg)", type=["pdf", "png", "jpg"])
            
            if uploaded_file and st.button("Extract Text"):
                temp_path = os.path.join(TEMP_DIR, uploaded_file.name)
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                with st.spinner("Parsing digital layers and running OCR if needed..."):
                    extracted_raw = extract_text_from_file(temp_path, uploaded_file.type, ocr_engine)
                    st.session_state['raw_text'] = clean_document_text(extracted_raw)
                    st.session_state['reqs'] = [] # Reset old reqs
                    st.session_state['audit_results'] = {} # Reset old results
                    st.success("Text extracted successfully!")
                    st.rerun()

            # Phase 2: Extraction & Execution
            if st.session_state['raw_text']:
                st.subheader("Extracted Text")
                st.text_area("Raw Document Content", value=st.session_state['raw_text'], height=200, disabled=True)
                
                # Phase 3: Identify & Run
                col_run1, col_run2 = st.columns([1, 4])
                with col_run1:
                    if st.button("▶ Run Analysis", type="primary"):
                        # Isolate Requirements First
                        sentences = re.split(r'(?<=[.!?]) +', st.session_state['raw_text'])
                        keywords = ["shall", "should", "must", "needs to", "will", "required to"]
                        st.session_state['reqs'] = [s.strip().replace("\n", " ") for s in sentences if any(k in s.lower() for k in keywords) and len(s.strip()) > 15]
                        st.session_state['audit_results'] = {}
                        
                        if not st.session_state['reqs']:
                            st.warning("No compliance keywords (shall, must, etc.) found in the text.")
                        else:
                            # Phase 4: Real-Time Results Streaming
                            st.subheader("Analysis Progress")
                            progress_bar = st.progress(0.0)
                            status_text = st.empty()
                            results_container = st.container()
                            
                            total_reqs = len(st.session_state['reqs'])
                            
                            for idx, current_req in enumerate(st.session_state['reqs']):
                                progress = float((idx + 1) / total_reqs)
                                progress_bar.progress(progress)
                                status_text.write(f"Analyzing requirement {idx + 1} / {total_reqs}...")
                                
                                # ChromaDB Search
                                docs = db.similarity_search(current_req, k=1)
                                if docs:
                                    matched_doc = docs[0]
                                    source_filename = os.path.basename(matched_doc.metadata.get('source', 'Unknown'))
                                    clause_text = matched_doc.page_content
                                else:
                                    source_filename = "General Standards"
                                    clause_text = "Standard Requirements Engineering Framework"
                                
                                # Llama Inference
                                pipeline_input = f"Req: {current_req}\nRule: {clause_text}"
                                prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\nAnalyze this software requirement against the matched framework standard rule.<|eot_id|><|start_header_id|>user<|end_header_id|>\n{pipeline_input}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
                                
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
                                
                                # Save to DB (Module 3.1)
                                log_audit_to_db(current_req, f"{source_filename} | {clause_text}", res)
                                
                                # Render to UI instantly
                                with results_container:
                                    with st.expander(f"✅ Requirement {idx + 1} Analyzed", expanded=True):
                                        st.write(f"**Original:** {current_req}")
                                        st.caption(f"**Matched Rule ({source_filename}):** {format_scannable_clause(clause_text, 150)}")
                                        st.markdown("---")
                                        st.write(f"**AI Evaluation:** {final_analysis}")
                                        st.success(f"**Suggested Rewrite:** {final_rewrite}")
                                
                                # Clean memory
                                del inputs, outputs
                                torch.cuda.empty_cache()
                                gc.collect()
                                
                            status_text.success(f"Batch audit of {total_reqs} requirements complete!")

        # =====================================================================
        # MODULE 4: HISTORY TAB (Read-Only)
        # =====================================================================
        with tabs[1]:
            st.header("Document History")
            st.write("View past submitted requirements and their verified results.")
            
            history_df = fetch_user_history()
            if history_df.empty:
                st.info("No verified history available yet.")
            else:
                st.dataframe(
                    history_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "timestamp": "Date Processed",
                        "requirement": "Target Requirement",
                        "status": "Audit Status"
                    }
                )

        # =====================================================================
        # MODULE 5: ADMIN DASHBOARD (Role-Restricted)
        # =====================================================================
        if admin_tab:
            with admin_tab:
                st.header("Admin Validation Hub")
                st.subheader("Data Flywheel Curation Matrix")
                
                unvalidated_df = fetch_unvalidated_logs()
                
                if unvalidated_df.empty:
                    st.success("✨ All logged transactions have been successfully validated!")
                else:
                    st.info(f"📥 Found {len(unvalidated_df)} pending transactions awaiting validation.")
                    
                    selected_log_id = st.selectbox(
                        "Select Log ID to inspect and commit to Training Pool:",
                        options=unvalidated_df["id"].tolist(),
                        format_func=lambda x: f"Log ID #{x} - {unvalidated_df[unvalidated_df['id'] == x]['requirement'].values[0][:60]}..."
                    )
                    
                    if selected_log_id:
                        row_data = unvalidated_df[unvalidated_df["id"] == selected_log_id].iloc[0]
                        
                        with st.form(key=f"validation_form_{selected_log_id}"):
                            st.text_area("❌ Original Requirement:", value=row_data["requirement"], disabled=True)
                            st.text_area("📖 Matched Rule:", value=row_data["matched_rule"], disabled=True)
                            
                            edited_output = st.text_area(
                                "Model Evaluation Output (Editable for Ground Truth):", 
                                value=row_data["model_output"], 
                                height=250
                            )
                            
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                if st.form_submit_button("✅ Approve & Export for Training", type="primary", use_container_width=True):
                                    update_log_status(selected_log_id, validated_text=edited_output, status="Validated")
                                    st.success(f"Log ID #{selected_log_id} appended to JSONL training data!")
                                    st.rerun()
                            with col_btn2:
                                if st.form_submit_button("🗑️ Reject & Delete Log", use_container_width=True):
                                    delete_log_entry(selected_log_id)
                                    st.warning("Log purged.")
                                    st.rerun()
    else:
        # Shown if user visits page without logging in
        st.info("Please Login or Sign Up to access the SpecGuard workspace.")

if __name__ == "__main__":
    main()