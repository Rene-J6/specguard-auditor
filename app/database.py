import os
import json
import sqlite3
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash

# =====================================================================
# PATH RESOLUTIONS
# =====================================================================
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)

SQLITE_DB_PATH = os.path.join(PROJECT_ROOT, "storage", "training_pool.db")
AUTH_DB_PATH = os.path.join(PROJECT_ROOT, "storage", "auth.db")
EXPORT_JSONL_PATH = os.path.join(PROJECT_ROOT, "data", "training", "dataset.jsonl")

# =====================================================================
# MODULE 1: USER MANAGEMENT & AUTHENTICATION (auth.db)
# =====================================================================
def init_auth_db():
    """Initializes the User Management database to store credentials safely."""
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT DEFAULT 'User'
        )
    """)
    
    # Secure profile migrations: Add Phone Number and Company Name dynamically
    for col_name in ["phone_number", "company_name"]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} TEXT")
        except sqlite3.OperationalError:
            pass # Column already exists
            
    conn.commit()
    conn.close()

def register_user(username, password, full_name, email, role="User", phone_number="", company_name=""):
    """Hashes the password and saves a new user account with personal info."""
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256:10000')
    
    try:
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, email, role, phone_number, company_name) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (username, hashed_pw, full_name, email, role, phone_number, company_name))
        conn.commit()
        return True, "Account registered successfully!"
    except sqlite3.IntegrityError:
        return False, "Username already exists. Please choose another."
    finally:
        conn.close()

def verify_login(username_or_email: str, password: str):
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, password_hash, role, full_name 
            FROM users 
            WHERE username = ? OR email = ?
        """, (username_or_email, username_or_email))
        row = cursor.fetchone()
        
        if row and check_password_hash(row[1], password):
            user_id = row[0]
            current_hash = row[1]
            
            if not current_hash.startswith('pbkdf2:sha256:10000'):
                new_fast_hash = generate_password_hash(password, method='pbkdf2:sha256:10000')
                cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_fast_hash, user_id))
                conn.commit()
                
            return True, row[2], row[3]
            
    except sqlite3.Error as e:
        print(f"Auth database error: {e}")
    finally:
        conn.close()
    return False, None, None

# =====================================================================
# MODULE 3: AUDIT LOGS & DATA FLYWHEEL (training_pool.db)
# =====================================================================
def init_sqlite_pool():
    """Initializes and migrates the local database to support expert metadata schema."""
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    # Base table creation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            requirement TEXT,
            matched_rule TEXT,
            model_output TEXT,
            status TEXT DEFAULT 'Pending',
            is_validated INTEGER DEFAULT 0,
            username TEXT 
        )
    """)
    
    # Staging & Notification Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            document_id TEXT NOT NULL,
            document_name TEXT NOT NULL,
            expert_username TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Schema migration checks: add new tracking columns dynamically to handle upgrades
    columns_to_add = [
        ("username", "TEXT"),
        ("document_id", "TEXT"),
        ("document_name", "TEXT"),
        ("review_status", "TEXT DEFAULT 'Pending'"),
        ("assigned_expert", "TEXT"),
        ("expert_evaluation", "TEXT"),
        ("expert_rewrite", "TEXT")
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE audit_logs ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass # Column already exists
    
    conn.commit()
    conn.close()
    
def log_audit_to_db(username, bad_req, doc_ref, raw_ai_output, document_id=None, document_name=None):
    """Caches real-time audit parameters with grouping pointers for multi-sentence sets."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_logs (
            username, requirement, matched_rule, model_output, 
            status, is_validated, document_id, document_name, review_status
        )
        VALUES (?, ?, ?, ?, 'Pending', 0, ?, ?, 'Pending')
    """, (username, bad_req, doc_ref, raw_ai_output, document_id, document_name))
    conn.commit()
    conn.close()

def fetch_unvalidated_logs():
    """Fetches raw logged logs awaiting classic admin validation."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    query = """
        SELECT id, timestamp, requirement, matched_rule, model_output 
        FROM audit_logs 
        WHERE is_validated = 0 OR status = 'Pending'
    """
    try:
        df = pd.read_sql_query(query, conn)
        df = df.where(pd.notnull(df), None)
    except Exception as e:
        print(f"Database read issue: {e}")
        df = pd.DataFrame(columns=["id", "timestamp", "requirement", "matched_rule", "model_output"])
    finally:
        conn.close()
    return df

def update_log_status(log_id: int, validated_text: str, status: str = "Validated"):
    """Saves raw admin-level corrections and appends results directly to the fine-tuning pool."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT requirement, matched_rule FROM audit_logs WHERE id = ?", (log_id,))
        row = cursor.fetchone()
        
        cursor.execute("""
            UPDATE audit_logs 
            SET model_output = ?,
                status = ?,
                is_validated = 1
            WHERE id = ?
        """, (validated_text, status, log_id))
        conn.commit()

        if row:
            req, rule = row
            os.makedirs(os.path.dirname(EXPORT_JSONL_PATH), exist_ok=True)
            with open(EXPORT_JSONL_PATH, "a", encoding="utf-8") as f:
                json_record = {
                    "instruction": f"Analyze this software requirement against the matched framework standard rule.\nReq: {req}\nRule: {rule}",
                    "output": validated_text
                }
                f.write(json.dumps(json_record) + "\n")
    except sqlite3.Error as e:
        print(f"Database error during log status update: {e}")
    finally:
        conn.close()

def delete_log_entry(log_id: int):
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM audit_logs WHERE id = ?", (log_id,))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error during log purge: {e}")
    finally:
        conn.close()
 
def fetch_user_history(username: str):
    """Fetches user logs including document grouping metadata, keeping expert IDs hidden."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    query = """
        SELECT id, timestamp, requirement, matched_rule, status, document_id, document_name, model_output 
        FROM audit_logs 
        WHERE username = ?
        ORDER BY timestamp DESC
    """
    try:
        df = pd.read_sql_query(query, conn, params=(username,))
        df = df.where(pd.notnull(df), None)
    except Exception as e:
        print(f"Database read issue: {e}")
        df = pd.DataFrame(columns=["id", "timestamp", "requirement", "matched_rule", "status", "document_id", "document_name", "model_output"])
    finally:
        conn.close()
    return df

def get_user_details(username: str):
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, email, role, phone_number, company_name FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "full_name": row[0], 
            "email": row[1], 
            "role": row[2], 
            "phone_number": row[3] or "", 
            "company_name": row[4] or ""
        }
    return None

def update_user_profile(username: str, full_name: str, email: str, phone_number: str = "", company_name: str = "", password: str = None):
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    try:
        # Standard Profile fields update
        cursor.execute("""
            UPDATE users 
            SET full_name = ?, email = ?, phone_number = ?, company_name = ? 
            WHERE username = ?
        """, (full_name, email, phone_number, company_name, username))
        
        # Optional Password hashing and update
        if password and password.strip() != "":
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256:10000')
            cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hashed_pw, username))
            
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Profile update error: {e}")
        return False
    finally:
        conn.close()

# =====================================================================
# NEW DOMAIN EXPERT CORE LOGIC (Expert Queue & Staging Flywheel)
# =====================================================================
def fetch_expert_queue(expert_username: str):
    """Fetches document sets that are either pending or exclusively locked by this expert."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT document_id, document_name, username, MAX(timestamp) as last_updated, review_status, assigned_expert
        FROM audit_logs
        WHERE review_status = 'Pending' OR (review_status = 'Locked' AND assigned_expert = ?)
        GROUP BY document_id
        ORDER BY last_updated DESC
    """, (expert_username,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "document_id": r[0],
            "document_name": r[1],
            "submitter": r[2],
            "timestamp": r[3],
            "review_status": r[4],
            "assigned_expert": r[5]
        } for r in rows
    ]

def fetch_document_requirements(document_id: str):
    """Fetches individual requirements grouped inside a single target document container."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, requirement, matched_rule, model_output, expert_evaluation, expert_rewrite
        FROM audit_logs
        WHERE document_id = ?
    """, (document_id,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "requirement": r[1],
            "matched_rule": r[2],
            "model_output": r[3],
            "expert_evaluation": r[4] or "",
            "expert_rewrite": r[5] or ""
        } for r in rows
    ]

def lock_requirement_set(document_id: str, expert_username: str):
    """Exclusively locks a document set to a single expert, hiding it from other queue experts."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_logs
        SET review_status = 'Locked', assigned_expert = ?
        WHERE document_id = ? AND review_status = 'Pending'
    """, (expert_username, document_id))
    rows_updated = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_updated > 0

def unlock_requirement_set(document_id: str, expert_username: str):
    """Releases an active lock on a document set, returning it back to the pending pool."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_logs
        SET review_status = 'Pending', assigned_expert = NULL
        WHERE document_id = ? AND assigned_expert = ? AND review_status = 'Locked'
    """, (document_id, expert_username))
    rows_updated = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_updated > 0

def parse_model_output_python(output):
    analysis = output or ""
    rewrite = "No rewrite suggested."
    if output and "### Suggested Rewrite" in output:
        parts = output.split("### Suggested Rewrite")
        analysis = parts[0].replace("### Analysis", "").strip()
        rewrite = parts[1].strip()
    return analysis, rewrite

def submit_expert_review(document_id: str, expert_username: str, reviews: list, is_approved: bool):
    """Finalizes expert reviews. Pushes alerts ONLY if the expert made manual corrections."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username, document_name FROM audit_logs WHERE document_id = ? LIMIT 1", (document_id,))
        row = cursor.fetchone()
        if not row:
            return False
        submitter, document_name = row

        if not is_approved:
            # Wipes the rejected document completely from the audit logs
            cursor.execute("DELETE FROM audit_logs WHERE document_id = ?", (document_id,))
            conn.commit()
            return True

        any_changes = False

        # Process approved evaluations
        for rev in reviews:
            req_id = rev["id"]
            expert_eval = rev["expert_evaluation"]
            expert_rew = rev["expert_rewrite"]
            
            # Check if there are any manual expert edits compared to original AI outputs
            cursor.execute("SELECT model_output FROM audit_logs WHERE id = ?", (req_id,))
            meta = cursor.fetchone()
            if meta:
                raw_output = meta[0]
                ai_eval, ai_rew = parse_model_output_python(raw_output)
                if (expert_eval.strip() != ai_eval.strip()) or (expert_rew.strip() != ai_rew.strip()):
                    any_changes = True

            cursor.execute("""
                UPDATE audit_logs
                SET expert_evaluation = ?,
                    expert_rewrite = ?,
                    review_status = 'Approved',
                    is_validated = 1,
                    status = 'Validated'
                WHERE id = ? AND document_id = ?
            """, (expert_eval, expert_rew, req_id, document_id))
            
            # Export corrected Ground Truth block to JSONL
            if meta:
                req, rule = meta[0], "" # Placeholder if rule retrieval failed
                cursor.execute("SELECT matched_rule FROM audit_logs WHERE id = ?", (req_id,))
                rule_row = cursor.fetchone()
                if rule_row:
                    rule = rule_row[0]
                os.makedirs(os.path.dirname(EXPORT_JSONL_PATH), exist_ok=True)
                with open(EXPORT_JSONL_PATH, "a", encoding="utf-8") as f:
                    json_record = {
                        "instruction": f"Analyze this software requirement against the matched framework standard rule.\nReq: {req}\nRule: {rule}",
                        "output": f"### Analysis\n{expert_eval}\n\n### Suggested Rewrite\n{expert_rew}"
                    }
                    f.write(json.dumps(json_record) + "\n")

        # 🔔 TARGETED CURATION ALERT: Log notification alert ONLY if the expert made custom changes
        if any_changes:
            cursor.execute("""
                INSERT INTO notifications (username, document_id, document_name, expert_username, message)
                VALUES (?, ?, ?, ?, ?)
            """, (
                submitter, 
                document_id, 
                document_name, 
                expert_username, 
                f"Expert {expert_username} completed auditing '{document_name}' and published improvements."
            ))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"Error submitting expert review: {e}")
        return False
    finally:
        conn.close()

def fetch_user_notifications(username: str):
    """Fetches document-level notification logs for standard users."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, document_id, document_name, expert_username, message, is_read, timestamp
        FROM notifications
        WHERE username = ?
        ORDER BY timestamp DESC
    """, (username,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "document_id": r[1],
            "document_name": r[2],
            "expert_username": r[3],
            "message": r[4],
            "is_read": r[5],
            "timestamp": r[6]
        } for r in rows
    ]

def mark_notification_as_read(notification_id: int):
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
    conn.commit()
    conn.close()

def delete_notification(notification_id: int):
    """Deletes an unread/read alert entirely from the Relational storage."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
    conn.commit()
    conn.close()

def fetch_document_comparison(document_id: str, username: str):
    """Retrieves comparative requirements. Shows ONLY the specific blocks modified by the expert."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, requirement, matched_rule, model_output, expert_evaluation, expert_rewrite
        FROM audit_logs
        WHERE document_id = ? AND username = ? AND review_status = 'Approved'
    """, (document_id, username))
    rows = cursor.fetchall()
    conn.close()
    
    comparisons = []
    for r in rows:
        req_id, req, rule, raw_output, exp_eval, exp_rew = r
        ai_eval, ai_rew = parse_model_output_python(raw_output)
        
        # Check if the expert made manual edits
        is_changed = (exp_eval.strip() != ai_eval.strip()) or (exp_rew.strip() != ai_rew.strip())
        
        if is_changed:
            comparisons.append({
                "id": req_id,
                "requirement": req,
                "matched_rule": rule,
                "model_output": raw_output,
                "expert_evaluation": exp_eval,
                "expert_rewrite": exp_rew,
                "ai_evaluation": ai_eval,
                "ai_rewrite": ai_rew
            })
    return comparisons

def fetch_expert_audited_logs(expert_username: str):
    """Fetches historical review logs curated by the current active expert."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT document_id, document_name, username, MAX(timestamp) as audited_at
        FROM audit_logs
        WHERE review_status = 'Approved' AND assigned_expert = ?
        GROUP BY document_id
        ORDER BY audited_at DESC
    """, (expert_username,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "document_id": r[0],
            "document_name": r[1],
            "submitter": r[2],
            "timestamp": r[3]
        } for r in rows
    ]

# =====================================================================
# NEW ADMINISTRATIVE AUDIT HUB LOGIC
# =====================================================================
def fetch_all_admin_logs():
    """Fetches all system logs, grouping them into standard pending entries and approved audits."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, timestamp, requirement, matched_rule, model_output, username, review_status, assigned_expert
        FROM audit_logs
        WHERE review_status IS NULL OR review_status = 'Pending' OR review_status = 'Locked'
        ORDER BY timestamp DESC
    """)
    pending_rows = cursor.fetchall()
    
    cursor.execute("""
        SELECT id, timestamp, requirement, matched_rule, model_output, username, expert_evaluation, expert_rewrite, assigned_expert, document_name
        FROM audit_logs
        WHERE review_status = 'Approved'
        ORDER BY timestamp DESC
    """)
    approved_rows = cursor.fetchall()
    conn.close()
    
    pending_list = [
        {
            "id": r[0],
            "timestamp": r[1],
            "requirement": r[2],
            "matched_rule": r[3],
            "model_output": r[4],
            "username": r[5],
            "review_status": r[6] or "Pending",
            "assigned_expert": r[7] or ""
        } for r in pending_rows
    ]
    
    approved_list = [
        {
            "id": r[0],
            "timestamp": r[1],
            "requirement": r[2],
            "matched_rule": r[3],
            "model_output": r[4],
            "username": r[5],
            "expert_evaluation": r[6] or "",
            "expert_rewrite": r[7] or "",
            "assigned_expert": r[8] or "",
            "document_name": r[9] or "Untitled"
        } for r in approved_rows
    ]
    
    return {
        "pending": pending_list,
        "approved": approved_list
    }