import os
import sqlite3

# Resolve absolute workspace paths dynamically
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
SQLITE_DB_PATH = os.path.join(PROJECT_ROOT, "storage", "training_pool.db")
EXPORT_JSONL_PATH = os.path.join(PROJECT_ROOT, "data", "training", "dataset.jsonl")

def init_sqlite_pool():
    """Initializes a local database to store pending training samples."""
    # FIX: Explicitly create the storage folder on your drive if it's missing
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bad_requirement TEXT,
            document_reference TEXT,
            analysis TEXT,
            suggested_rewrite TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)
    conn.commit()
    conn.close()
    
def log_audit_to_db(bad_req, doc_ref, raw_ai_output):
    """Parses raw AI text strings and caches them into the shadow data pool."""
    analysis = raw_ai_output
    suggested_rewrite = ""
    
    if "### Suggested Rewrite" in raw_ai_output:
        parts = raw_ai_output.split("### Suggested Rewrite")
        analysis = parts[0].replace("### Analysis", "").strip()
        suggested_rewrite = parts[1].strip()

    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pending_pool (bad_requirement, document_reference, analysis, suggested_rewrite, status)
        VALUES (?, ?, ?, ?, 'Pending')
    """, (bad_req, doc_ref, analysis, suggested_rewrite))
    conn.commit()
    conn.close()