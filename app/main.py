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
    register_user, verify_login, fetch_user_history,
    get_user_details, update_user_profile  # Make sure this is added to database.py!
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

if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Dashboard"
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
# GLOBAL RESOURCE INITIALIZATION (Fixes Post-Login Freeze)
# =====================================================================
# Moving this outside the login block ensures models load on startup, not on login
try:
    with st.spinner("Initializing SpecGuard AI Framework Engine Core..."):
        model, tokenizer, ocr_engine, db = load_pipeline_resources()
except Exception as e:
    st.error(f"Critical System Initialization Failure: {e}")

# =====================================================================
# MODULE 1: AUTHENTICATION MODAL
# =====================================================================
def render_login_page():
    # Use columns to push the login box to the center of the screen
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<h2 style='text-align: center;'>Welcome to SpecGuard</h2>", unsafe_allow_html=True)
        st.markdown("---")
        
        tab_login, tab_register = st.tabs(["🔑 Login", "📝 Sign Up"])
    
    with tab_login:
        # Wrapping in a form removes "Press Enter to apply" completely
        with st.form(key="login_form_clear"):
            st.subheader("Account Login")
            log_username = st.text_input("Username or Email", key="auth_login_user")
            log_password = st.text_input("Password", type="password", key="auth_login_pass")
            submit_login = st.form_submit_button("Login", width='stretch', type="primary")
            
            if submit_login:
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
        with st.form(key="register_form_clear"):
            st.subheader("Create an Account")
            reg_fullname = st.text_input("Full Legal Name *", key="reg_val_name")
            reg_email = st.text_input("Department Email Address *", key="reg_val_email")
            reg_username = st.text_input("Desired Username *", key="reg_val_user")
            reg_password = st.text_input("Password *", type="password", key="reg_val_pass")
            reg_confirm = st.text_input("Confirm Password *", type="password", key="reg_val_conf")
            submit_reg = st.form_submit_button("Register", width='stretch', type="primary")
            
            if submit_reg:
                if not all([reg_fullname, reg_email, reg_username, reg_password, reg_confirm]):
                    st.error("All fields are required.")
                elif reg_password != reg_confirm:
                    st.error("Passwords do not match.")
                else:
                    success, message = register_user(reg_username, reg_password, reg_fullname, reg_email)
                    if success:
                        st.success("Registration successful! You can now use the Login tab.")
                    else:
                        st.error(message)

# =====================================================================
# MAIN LAYOUT & ROUTING
# =====================================================================
def main():

    # ✨ NEW: Global CSS to override Streamlit's default massive padding values and UI quirks
    st.markdown("""
        <style>
        /* Force the main page content area to sit tightly at the top of the screen */
        .block-container { padding-top: 2.5rem !important; padding-bottom: 0rem !important; }
        
        /* Reduce the massive spacing around standard columns */
        [data-testid="stHorizontalBlock"] { gap: 0rem !important; }
        
        /* Tighten up internal spacing inside the profile Popover dropdown container */
        div[data-testid="stPopoverBody"] { padding: 12px !important; }

        /* ✨ FIX 1: Hide the "Press Enter to submit form" helper text */
        [data-testid="InputInstructions"] { display: none !important; }

        /* ✨ FIX 2: Block Edge/Chrome from injecting a second native password eye icon */
        input[type="password"]::-ms-reveal,
        input[type="password"]::-ms-clear { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    # --- HEADER NAVIGATION ---
    header_col1, header_col2 = st.columns([7, 3])
    with header_col1:
        st.markdown("<h1 style='margin:0; padding:0; line-height:1.2;'>🛡️ SpecGuard</h1>", unsafe_allow_html=True)
    
    with header_col2:
        st.markdown("<div style='margin-top: 4px;'>", unsafe_allow_html=True)
        
        if st.session_state["logged_in"]:
            with st.popover(f"👤 {st.session_state['full_name']}", width='stretch'):
                st.markdown(f"<p style='margin: 0; padding: 0;'><b>Role:</b> {st.session_state['role']}</p>", unsafe_allow_html=True)
                st.markdown("<hr style='margin: 6px 0px 10px 0px; border: 0; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)
                if st.button("Personal Profile", width='stretch'):
                    st.session_state["current_page"] = "Profile"
                    st.rerun()
                if st.button("Logout", type="primary", width='stretch'):
                    st.session_state.clear()
                    st.rerun()
        else:
            # ✨ THE TRUE MAGIC SPACER: 
            # Matches the exact pixel height of a Streamlit button (38px) 
            # PLUS its hidden native bottom margin (16px).
            st.markdown("<div style='height: 38px; margin-bottom: 16px;'></div>", unsafe_allow_html=True)
            
        st.markdown("</div>", unsafe_allow_html=True)

    # ✨ THE UNIFIED DIVIDER: 
    # Because the row height is now locked, this single line works flawlessly on every page.
    st.markdown("<hr style='margin: -25px 0px 15px 0px; border: none; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)

    # =====================================================================
    # THE MASTER PAGE ROUTER
    # =====================================================================
    
    # 1. IF NOT LOGGED IN -> Show Login Page & Stop Rendering
    if not st.session_state["logged_in"]:
        render_login_page()
        return 

    # 2. IF LOGGED IN -> Show Profile
    if st.session_state["current_page"] == "Profile":
        st.header("👤 Personal Profile Settings")
        
        if st.button("← Back to Dashboard"):
            st.session_state["current_page"] = "Dashboard"
            st.rerun()
            
        st.markdown("---")
        
        user_data = get_user_details(st.session_state["username"])
        if user_data:
            col_prof1, col_prof2 = st.columns([1, 2])
            with col_prof1:
                with st.form("profile_edit_form"):
                    st.subheader("Edit Information")
                    edit_name = st.text_input("Full Name", value=user_data["full_name"])
                    edit_email = st.text_input("Email Address", value=user_data["email"])
                    st.text_input("System Role", value=user_data["role"], disabled=True)
                    
                    if st.form_submit_button("Save Changes", type="primary", use_container_width=True):
                        if update_user_profile(st.session_state["username"], edit_name, edit_email):
                            st.session_state["full_name"] = edit_name 
                            st.success("Profile updated successfully!")
                            st.rerun()
                        else:
                            st.error("Failed to update profile.")
        return # Stop rendering the rest of the app if on the Profile page

    # 3. IF LOGGED IN -> Show Dashboard
    if st.session_state["current_page"] == "Dashboard":

        if st.session_state["role"] == "Admin":
            tabs = st.tabs(["🔍 Analysis", "📜 History", "👑 Admin Dashboard"])
            admin_tab = tabs[2]
        else:
            tabs = st.tabs(["🔍 Analysis", "📜 History"])
            admin_tab = None

        # --- MODULE 2: ANALYSIS TAB ---
        with tabs[0]:
            # Using HTML removes Streamlit's massive default header margins
            st.markdown("<h3 style='margin-top: 5px; margin-bottom: 15px;'>Requirement Analysis Workspace</h3>", unsafe_allow_html=True)
            
            uploaded_file = st.file_uploader("Upload Specification Documents (.pdf, .png, .jpg)", type=["pdf", "png", "jpg"])
            
            if uploaded_file and st.button("Extract Text"):
                temp_path = os.path.join(TEMP_DIR, uploaded_file.name)
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                with st.spinner("Parsing digital layers and running OCR if needed..."):
                    extracted_raw = extract_text_from_file(temp_path, uploaded_file.type, ocr_engine)
                    st.session_state['raw_text'] = clean_document_text(extracted_raw)
                    st.session_state['reqs'] = []
                    st.session_state['audit_results'] = {}
                    st.success("Text extracted successfully!")
                    st.rerun()

            if st.session_state['raw_text']:
                st.subheader("Extracted Text")
                st.text_area("Raw Document Content", value=st.session_state['raw_text'], height=200, disabled=True)
                
                # Removed the [1, 4] columns here to give the button and results full width!
                if st.button("▶ Run Analysis", type="primary"):
                    sentences = re.split(r'(?<=[.!?]) +', st.session_state['raw_text'])
                    keywords = ["shall", "should", "must", "needs to", "will", "required to"]
                    st.session_state['reqs'] = [s.strip().replace("\n", " ") for s in sentences if any(k in s.lower() for k in keywords) and len(s.strip()) > 15]
                    st.session_state['audit_results'] = {}
                    
                    if not st.session_state['reqs']:
                        st.warning("No compliance keywords (shall, must, etc.) found in the text.")
                    else:
                        st.subheader("Analysis Progress")
                        progress_bar = st.progress(0.0)
                        status_text = st.empty()
                        results_container = st.container()
                        
                        total_reqs = len(st.session_state['reqs'])
                        
                        for idx, current_req in enumerate(st.session_state['reqs']):
                            progress = float((idx + 1) / total_reqs)
                            progress_bar.progress(progress)
                            status_text.write(f"Analyzing requirement {idx + 1} / {total_reqs}...")
                            
                            docs = db.similarity_search(current_req, k=1)
                            if docs:
                                matched_doc = docs[0]
                                source_filename = os.path.basename(matched_doc.metadata.get('source', 'Unknown'))
                                clause_text = matched_doc.page_content
                            else:
                                source_filename = "General Standards"
                                clause_text = "Standard Requirements Engineering Framework"
                            
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
                            
                            log_audit_to_db(st.session_state["username"], current_req, f"{source_filename} | {clause_text}", res)
                            
                            # ✨ NEW HORIZONTAL LAYOUT ✨
                            with results_container:
                                with st.expander(f"✅ Requirement {idx + 1} Analyzed", expanded=True):
                                    # Split the expander into two horizontal columns
                                    res_col1, res_col2 = st.columns(2)
                                    with res_col1:
                                        st.markdown("**❌ Original Requirement:**")
                                        # ✨ Custom Blue Box that hugs the text perfectly
                                        st.markdown(f"<div style='background-color: #eef4ff; color: #004fb0; padding: 12px 16px; border-radius: 8px; width: fit-content; margin-bottom: 15px;'>{current_req}</div>", unsafe_allow_html=True)
                                        
                                        st.markdown(f"**📖 Matched Rule ({source_filename}):**")
                                        st.caption(format_scannable_clause(clause_text, 150))
                                        
                                    with res_col2:
                                        st.markdown("**🔍 AI Evaluation:**")
                                        st.write(final_analysis)
                                        st.markdown("**✅ Suggested Rewrite:**")
                                        # ✨ Custom Green Box that hugs the text perfectly
                                        st.markdown(f"<div style='background-color: #e6f4ea; color: #137333; padding: 12px 16px; border-radius: 8px; width: fit-content; margin-bottom: 15px;'>{final_rewrite}</div>", unsafe_allow_html=True)
                            
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
            
            history_df = fetch_user_history(st.session_state["username"]) 
            if history_df.empty:
                st.info("No verified history available yet.")
            else:
                st.dataframe(
                    history_df,
                    width='stretch',
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
                    st.markdown("---")
                    
                    # ✨ NEW UI: Creates a clickable row for every single pending log
                    for index, row_data in unvalidated_df.iterrows():
                        log_id = row_data["id"]
                        short_req = row_data["requirement"][:70] + "..." if len(row_data["requirement"]) > 70 else row_data["requirement"]
                        
                        # The Expander acts as the clickable row
                        with st.expander(f"🔹 Log #{log_id} | {row_data['timestamp']} | {short_req}"):
                            
                            with st.form(key=f"validation_form_{log_id}"):
                                st.text_area("❌ Original Requirement:", value=row_data["requirement"], disabled=True, height=100)
                                st.text_area("📖 Matched Rule:", value=row_data["matched_rule"], disabled=True, height=100)
                                
                                edited_output = st.text_area(
                                    "Model Evaluation Output (Editable for Ground Truth):", 
                                    value=row_data["model_output"], 
                                    height=200
                                )
                                
                                col_btn1, col_btn2 = st.columns(2)
                                with col_btn1:
                                    if st.form_submit_button("✅ Approve & Export for Training", type="primary", use_container_width=True):
                                        update_log_status(log_id, validated_text=edited_output, status="Validated")
                                        st.success(f"Log ID #{log_id} appended to JSONL training data!")
                                        st.rerun()
                                with col_btn2:
                                    if st.form_submit_button("🗑️ Reject & Delete Log", use_container_width=True):
                                        delete_log_entry(log_id)
                                        st.warning("Log purged.")
                                        st.rerun()

if __name__ == "__main__":
    main()