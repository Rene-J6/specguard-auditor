import os
import json
import sqlite3
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash

# =====================================================================
# PATH RESOLUTIONS
# =====================================================================
# Resolve absolute workspace paths dynamically
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)

# Database file paths
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
    
    # Expanded users table to collect required personal information
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
    conn.commit()
    conn.close()

def register_user(username, password, full_name, email, role="User"):
    """Hashes the password and saves a new user account with personal info."""
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    
    hashed_pw = generate_password_hash(password)
    
    try:
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, email, role) 
            VALUES (?, ?, ?, ?, ?)
        """, (username, hashed_pw, full_name, email, role))
        conn.commit()
        return True, "Account registered successfully!"
    except sqlite3.IntegrityError:
        return False, "Username already exists. Please choose another."
    finally:
        conn.close()

def verify_login(username, password):
    """Checks the database and returns validation status, role, and full name."""
    conn = sqlite3.connect(AUTH_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT password_hash, role, full_name FROM users WHERE username = ?", (username,))
    user_record = cursor.fetchone()
    conn.close()
    
    if user_record:
        stored_hash, role, full_name = user_record
        if check_password_hash(stored_hash, password):
            # Return True, plus the user's role and full name for the UI
            return True, role, full_name
            
    return False, None, None

# =====================================================================
# MODULE 3: AUDIT LOGS & DATA FLYWHEEL (training_pool.db)
# =====================================================================
def init_sqlite_pool():
    """Initializes a local database to store pending training samples."""
    # Explicitly create the storage folder on your drive if it's missing
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            requirement TEXT,
            matched_rule TEXT,
            model_output TEXT,
            status TEXT DEFAULT 'Pending',
            is_validated INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    
def log_audit_to_db(bad_req, doc_ref, raw_ai_output):
    """Parses raw AI text strings and caches them into the shadow data pool."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_logs (requirement, matched_rule, model_output, status, is_validated)
        VALUES (?, ?, ?, 'Pending', 0)
    """, (bad_req, doc_ref, raw_ai_output))
    conn.commit()
    conn.close()

def fetch_unvalidated_logs():
    """Fetches all logged transactions that haven't been reviewed yet."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    query = """
        SELECT id, timestamp, requirement, matched_rule, model_output 
        FROM audit_logs 
        WHERE is_validated = 0 OR status = 'Pending'
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"Database read issue handled: {e}")
        df = pd.DataFrame(columns=["id", "timestamp", "requirement", "matched_rule", "model_output"])
    finally:
        conn.close()
    return df

def update_log_status(log_id: int, validated_text: str, status: str = "Validated"):
    """
    Updates a pending log entry with the verified ground-truth text, marks it
    as validated, and prepares it for the fine-tuning training dataset pool (Module 3.5).
    """
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    cursor = conn.cursor()
    
    try:
        # Fetch the requirement and rule for the JSONL export before updating
        cursor.execute("SELECT requirement, matched_rule FROM audit_logs WHERE id = ?", (log_id,))
        row = cursor.fetchone()
        
        # We update both the final model text field and the verification tracking flags
        cursor.execute("""
            UPDATE audit_logs 
            SET model_output = ?,
                status = ?,
                is_validated = 1
            WHERE id = ?
        """, (validated_text, status, log_id))
        conn.commit()

        # Module 3.5: Training Data Submodule - Export to JSONL
        if row:
            req, rule = row
            os.makedirs(os.path.dirname(EXPORT_JSONL_PATH), exist_ok=True)
            with open(EXPORT_JSONL_PATH, "a", encoding="utf-8") as f:
                # Structuring as an instruction-tuning dataset block
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
    """
    Purges a flawed, corrupted, or duplicate user interaction entry 
    completely from the evaluation log matrix pool.
    """
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM audit_logs 
            WHERE id = ?
        """, (log_id,))
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error during log purge: {e}")
    finally:
        conn.close()
 
def fetch_user_history():
    """Fetches all validated logs to display in the User History tab."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    query = """ 
        SELECT timestamp, requirement, matched_rule, status 
        FROM audit_logs 
        WHERE is_validated = 1 OR status = 'Validated'
        ORDER BY timestamp DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"Database read issue handled: {e}")
        df = pd.DataFrame(columns=["timestamp", "requirement", "matched_rule", "status"])
    finally:
        conn.close()
    return df