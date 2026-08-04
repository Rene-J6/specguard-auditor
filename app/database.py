import os
import json
import hashlib
import shutil
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

LIFECYCLE_PENDING = "PENDING"
LIFECYCLE_LOCKED = "LOCKED"
LIFECYCLE_APPROVED = "APPROVED"
LIFECYCLE_REJECTED = "REJECTED"
VALID_LIFECYCLE_STATUSES = {
    LIFECYCLE_PENDING,
    LIFECYCLE_LOCKED,
    LIFECYCLE_APPROVED,
    LIFECYCLE_REJECTED,
}
TRAINING_FIELDS = (
    "bad_requirement",
    "document_reference",
    "analysis",
    "suggested_rewrite",
)
LIFECYCLE_SCHEMA_VERSION = 2


def _connect_pool():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _canonical_training_record(requirement, matched_rule, analysis, rewrite):
    return {
        "bad_requirement": requirement or "",
        "document_reference": matched_rule or "",
        "analysis": analysis or "",
        "suggested_rewrite": rewrite or "",
    }


def _canonical_json(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_hash(record):
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def _load_training_records():
    if not os.path.exists(EXPORT_JSONL_PATH):
        return []

    records = []
    with open(EXPORT_JSONL_PATH, "r", encoding="utf-8") as dataset_file:
        for line_number, line in enumerate(dataset_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on dataset line {line_number}: {exc}") from exc
            if not isinstance(record, dict) or set(record.keys()) != set(TRAINING_FIELDS):
                raise ValueError(
                    f"Dataset line {line_number} does not use the required four-field schema."
                )
            records.append({field: record[field] for field in TRAINING_FIELDS})
    return records


def _write_training_records(records):
    os.makedirs(os.path.dirname(EXPORT_JSONL_PATH), exist_ok=True)
    temp_path = f"{EXPORT_JSONL_PATH}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as dataset_file:
            for record in records:
                dataset_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            dataset_file.flush()
            os.fsync(dataset_file.fileno())
        os.replace(temp_path, EXPORT_JSONL_PATH)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

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
    """Initializes the pool and applies the versioned lifecycle migration."""
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    database_existed = os.path.exists(SQLITE_DB_PATH)
    conn = _connect_pool()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            requirement TEXT,
            matched_rule TEXT,
            model_output TEXT,
            username TEXT,
            document_id TEXT,
            document_name TEXT,
            lifecycle_status TEXT NOT NULL DEFAULT 'PENDING',
            assigned_expert TEXT,
            expert_evaluation TEXT,
            expert_rewrite TEXT
        )
    """)

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    current_version = cursor.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()[0]

    if current_version < LIFECYCLE_SCHEMA_VERSION:
        conn.commit()
        conn.close()
        if database_existed:
            backup_path = os.path.join(
                os.path.dirname(SQLITE_DB_PATH),
                "training_pool.pre_lifecycle_v2.backup.db",
            )
            if not os.path.exists(backup_path):
                shutil.copy2(SQLITE_DB_PATH, backup_path)
        conn = _connect_pool()
        _apply_lifecycle_migration(conn)

    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_exports (
            audit_log_id INTEGER PRIMARY KEY,
            record_hash TEXT NOT NULL,
            record_json TEXT NOT NULL,
            export_status TEXT NOT NULL DEFAULT 'PENDING',
            owns_dataset_line INTEGER NOT NULL DEFAULT 0,
            exported_at DATETIME,
            FOREIGN KEY (audit_log_id) REFERENCES audit_logs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_lifecycle ON audit_logs(lifecycle_status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_document ON audit_logs(document_id)"
    )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_expert_lock
        ON audit_logs(assigned_expert, lifecycle_status)
    """)
    conn.commit()
    conn.close()

    _reconcile_approved_exports()


def _apply_lifecycle_migration(conn):
    """Maps legacy audit status fields into the canonical lifecycle column."""
    cursor = conn.cursor()
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(audit_logs)")}
    if "lifecycle_status" not in columns:
        cursor.execute(
            "ALTER TABLE audit_logs ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'PENDING'"
        )

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(audit_logs)")}
    approved_conditions = []
    locked_conditions = []
    if "review_status" in columns:
        approved_conditions.append("UPPER(COALESCE(review_status, '')) = 'APPROVED'")
        locked_conditions.append("UPPER(COALESCE(review_status, '')) = 'LOCKED'")
    if "status" in columns:
        approved_conditions.append("UPPER(COALESCE(status, '')) = 'VALIDATED'")
    if "is_validated" in columns:
        approved_conditions.append("COALESCE(is_validated, 0) = 1")

    approved_sql = " OR ".join(approved_conditions) or "0"
    locked_sql = " OR ".join(locked_conditions) or "0"
    cursor.execute(f"""
        UPDATE audit_logs
        SET lifecycle_status = CASE
            WHEN {approved_sql} THEN 'APPROVED'
            WHEN {locked_sql} THEN 'LOCKED'
            ELSE 'PENDING'
        END
    """)

    # A document is one review unit, so every requirement must share one status.
    document_ids = [
        row[0]
        for row in cursor.execute(
            "SELECT DISTINCT document_id FROM audit_logs WHERE document_id IS NOT NULL"
        )
    ]
    for document_id in document_ids:
        rows = cursor.execute(
            """
            SELECT lifecycle_status, assigned_expert
            FROM audit_logs WHERE document_id = ?
            """,
            (document_id,),
        ).fetchall()
        statuses = {row[0] for row in rows}
        if LIFECYCLE_APPROVED in statuses:
            normalized_status = LIFECYCLE_APPROVED
        elif LIFECYCLE_LOCKED in statuses:
            normalized_status = LIFECYCLE_LOCKED
        else:
            normalized_status = LIFECYCLE_PENDING
        expert = next((row[1] for row in rows if row[1]), None)
        cursor.execute(
            """
            UPDATE audit_logs
            SET lifecycle_status = ?, assigned_expert = ?
            WHERE document_id = ?
            """,
            (
                normalized_status,
                expert if normalized_status != LIFECYCLE_PENDING else None,
                document_id,
            ),
        )

    # Legacy data may contain several locks for one expert. Keep only the newest.
    experts = cursor.execute("""
        SELECT assigned_expert
        FROM audit_logs
        WHERE lifecycle_status = 'LOCKED' AND assigned_expert IS NOT NULL
        GROUP BY assigned_expert
        HAVING COUNT(DISTINCT document_id) > 1
    """).fetchall()
    for expert_row in experts:
        expert = expert_row[0]
        locked_documents = cursor.execute("""
            SELECT document_id, MAX(timestamp) AS latest
            FROM audit_logs
            WHERE lifecycle_status = 'LOCKED' AND assigned_expert = ?
            GROUP BY document_id
            ORDER BY latest DESC
        """, (expert,)).fetchall()
        for stale_document in locked_documents[1:]:
            cursor.execute("""
                UPDATE audit_logs
                SET lifecycle_status = 'PENDING', assigned_expert = NULL
                WHERE document_id = ?
            """, (stale_document[0],))

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_exports (
            audit_log_id INTEGER PRIMARY KEY,
            record_hash TEXT NOT NULL,
            record_json TEXT NOT NULL,
            export_status TEXT NOT NULL DEFAULT 'PENDING',
            owns_dataset_line INTEGER NOT NULL DEFAULT 0,
            exported_at DATETIME,
            FOREIGN KEY (audit_log_id) REFERENCES audit_logs(id) ON DELETE CASCADE
        )
    """)
    cursor.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (LIFECYCLE_SCHEMA_VERSION,),
    )
    conn.commit()


def _register_export_rows(conn, audit_rows, existing_hashes):
    cursor = conn.cursor()
    known_hashes = set(existing_hashes)
    known_hashes.update(
        row[0]
        for row in cursor.execute(
            "SELECT record_hash FROM training_exports WHERE owns_dataset_line = 1"
        )
    )
    for row in audit_rows:
        record = _canonical_training_record(
            row["requirement"],
            row["matched_rule"],
            row["expert_evaluation"],
            row["expert_rewrite"],
        )
        record_json = _canonical_json(record)
        fingerprint = _record_hash(record)
        owns_line = 0 if fingerprint in known_hashes else 1
        cursor.execute("""
            INSERT OR IGNORE INTO training_exports (
                audit_log_id, record_hash, record_json, export_status, owns_dataset_line
            ) VALUES (?, ?, ?, 'PENDING', ?)
        """, (row["id"], fingerprint, record_json, owns_line))
        if owns_line:
            known_hashes.add(fingerprint)


def _process_pending_exports(document_id=None):
    records = _load_training_records()
    existing_hashes = {_record_hash(record) for record in records}
    conn = _connect_pool()
    try:
        params = []
        document_filter = ""
        if document_id is not None:
            document_filter = " AND a.document_id = ?"
            params.append(document_id)
        pending = conn.execute(f"""
            SELECT t.audit_log_id, t.record_hash, t.record_json, t.owns_dataset_line
            FROM training_exports t
            JOIN audit_logs a ON a.id = t.audit_log_id
            WHERE t.export_status = 'PENDING'{document_filter}
            ORDER BY t.audit_log_id
        """, params).fetchall()
        if not pending:
            return 0

        additions = 0
        for export_row in pending:
            if export_row["owns_dataset_line"] and export_row["record_hash"] not in existing_hashes:
                record = json.loads(export_row["record_json"])
                records.append({field: record[field] for field in TRAINING_FIELDS})
                existing_hashes.add(export_row["record_hash"])
                additions += 1

        if additions:
            _write_training_records(records)

        conn.executemany("""
            UPDATE training_exports
            SET export_status = 'EXPORTED', exported_at = CURRENT_TIMESTAMP
            WHERE audit_log_id = ?
        """, [(row["audit_log_id"],) for row in pending])
        conn.commit()
        return len(pending)
    finally:
        conn.close()


def _reconcile_approved_exports():
    records = _load_training_records()
    existing_hashes = {_record_hash(record) for record in records}
    conn = _connect_pool()
    try:
        approved_rows = conn.execute("""
            SELECT id, requirement, matched_rule, expert_evaluation, expert_rewrite
            FROM audit_logs
            WHERE lifecycle_status = 'APPROVED'
            ORDER BY id
        """).fetchall()
        _register_export_rows(conn, approved_rows, existing_hashes)
        conn.commit()
    finally:
        conn.close()
    _process_pending_exports()
    
def log_audit_to_db(username, bad_req, doc_ref, raw_ai_output, document_id=None, document_name=None):
    """Caches real-time audit parameters with grouping pointers for multi-sentence sets."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_logs (
            username, requirement, matched_rule, model_output, 
            document_id, document_name, lifecycle_status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
    """, (username, bad_req, doc_ref, raw_ai_output, document_id, document_name))
    conn.commit()
    conn.close()

def fetch_unvalidated_logs():
    """Fetches raw logged logs awaiting classic admin validation."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    query = """
        SELECT id, timestamp, requirement, matched_rule, model_output 
        FROM audit_logs 
        WHERE lifecycle_status IN ('PENDING', 'LOCKED')
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
    """Legacy admin validation is intentionally disabled."""
    raise RuntimeError("Admin validation has been removed; Expert approval is final.")

def delete_log_entry(log_id: int):
    return _delete_audit_records("id = ?", (log_id,))


def delete_document_entry(document_id: str):
    return _delete_audit_records("document_id = ?", (document_id,))


def _delete_audit_records(where_clause, params):
    """Deletes audit rows and revokes any dataset lines they own."""
    conn = _connect_pool()
    original_records = None
    dataset_changed = False
    try:
        rows = conn.execute(f"""
            SELECT id, document_id, lifecycle_status
            FROM audit_logs WHERE {where_clause}
        """, params).fetchall()
        if not rows:
            return {"success": False, "code": "NOT_FOUND"}

        approved_ids = [row["id"] for row in rows if row["lifecycle_status"] == LIFECYCLE_APPROVED]
        updated_records = None
        if approved_ids:
            placeholders = ",".join("?" for _ in approved_ids)
            exports = conn.execute(f"""
                SELECT audit_log_id, record_hash, export_status, owns_dataset_line
                FROM training_exports
                WHERE audit_log_id IN ({placeholders})
            """, approved_ids).fetchall()
            export_by_id = {row["audit_log_id"]: row for row in exports}
            for approved_id in approved_ids:
                export_row = export_by_id.get(approved_id)
                if not export_row or export_row["export_status"] != "EXPORTED":
                    return {"success": False, "code": "EXPORT_NOT_RECONCILED"}

            original_records = _load_training_records()
            updated_records = list(original_records)
            for export_row in exports:
                if not export_row["owns_dataset_line"]:
                    continue
                match_index = next(
                    (
                        index for index, record in enumerate(updated_records)
                        if _record_hash(record) == export_row["record_hash"]
                    ),
                    None,
                )
                if match_index is None:
                    return {"success": False, "code": "DATASET_RECORD_NOT_FOUND"}
                updated_records.pop(match_index)
            dataset_changed = updated_records != original_records
            if dataset_changed:
                _write_training_records(updated_records)

        row_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in row_ids)
        document_ids = {row["document_id"] for row in rows if row["document_id"]}
        conn.execute(f"DELETE FROM audit_logs WHERE id IN ({placeholders})", row_ids)
        for document_id in document_ids:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
            if remaining == 0:
                conn.execute("DELETE FROM notifications WHERE document_id = ?", (document_id,))
        conn.commit()
        return {"success": True, "deleted": len(row_ids)}
    except Exception as exc:
        conn.rollback()
        if dataset_changed and original_records is not None:
            _write_training_records(original_records)
        return {"success": False, "code": "DELETE_FAILED", "detail": str(exc)}
    finally:
        conn.close()
 
def fetch_user_history(username: str):
    """Fetches user-visible audit data without internal lifecycle metadata."""
    conn = sqlite3.connect(SQLITE_DB_PATH) 
    query = """
        SELECT id, timestamp, requirement, matched_rule, document_id, document_name, model_output
        FROM audit_logs 
        WHERE username = ?
        ORDER BY timestamp DESC
    """
    try:
        df = pd.read_sql_query(query, conn, params=(username,))
        df = df.where(pd.notnull(df), None)
    except Exception as e:
        print(f"Database read issue: {e}")
        df = pd.DataFrame(columns=["id", "timestamp", "requirement", "matched_rule", "document_id", "document_name", "model_output"])
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
    """Returns public pending work plus the caller's one active document."""
    conn = _connect_pool()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT document_id, MAX(document_name) AS document_name,
               MAX(username) AS username, MAX(timestamp) AS last_updated,
               lifecycle_status, MAX(assigned_expert) AS assigned_expert
        FROM audit_logs
        WHERE lifecycle_status = 'PENDING'
           OR (lifecycle_status = 'LOCKED' AND assigned_expert = ?)
        GROUP BY document_id, lifecycle_status
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
            "lifecycle_status": r[4],
            "assigned_expert": r[5]
        } for r in rows
    ]

def fetch_document_requirements(document_id: str, expert_username: str):
    """Returns review content only to the Expert assigned to the document."""
    conn = _connect_pool()
    cursor = conn.cursor()
    ownership = cursor.execute("""
        SELECT lifecycle_status, assigned_expert
        FROM audit_logs WHERE document_id = ? LIMIT 1
    """, (document_id,)).fetchone()
    if not ownership:
        conn.close()
        return {"success": False, "code": "NOT_FOUND", "requirements": []}
    if ownership["assigned_expert"] != expert_username or ownership["lifecycle_status"] not in {
        LIFECYCLE_LOCKED, LIFECYCLE_APPROVED, LIFECYCLE_REJECTED
    }:
        conn.close()
        return {"success": False, "code": "FORBIDDEN", "requirements": []}
    cursor.execute("""
        SELECT id, requirement, matched_rule, model_output, expert_evaluation, expert_rewrite
        FROM audit_logs
        WHERE document_id = ?
    """, (document_id,))
    rows = cursor.fetchall()
    conn.close()
    requirements = [
        {
            "id": r[0],
            "requirement": r[1],
            "matched_rule": r[2],
            "model_output": r[3],
            "expert_evaluation": r[4] or "",
            "expert_rewrite": r[5] or ""
        } for r in rows
    ]
    return {"success": True, "requirements": requirements}

def lock_requirement_set(document_id: str, expert_username: str):
    """Locks one pending document while enforcing one active lock per Expert."""
    conn = _connect_pool()
    cursor = conn.cursor()
    active = cursor.execute("""
        SELECT document_id, MAX(document_name) AS document_name
        FROM audit_logs
        WHERE lifecycle_status = 'LOCKED' AND assigned_expert = ?
        GROUP BY document_id
        ORDER BY MAX(timestamp) DESC
        LIMIT 1
    """, (expert_username,)).fetchone()
    if active:
        if active["document_id"] == document_id:
            conn.close()
            return {
                "success": True,
                "already_locked": True,
                "document_id": document_id,
                "document_name": active["document_name"],
            }
        conn.close()
        return {
            "success": False,
            "code": "ACTIVE_LOCK_EXISTS",
            "document_id": active["document_id"],
            "document_name": active["document_name"],
        }

    target = cursor.execute("""
        SELECT lifecycle_status FROM audit_logs WHERE document_id = ? LIMIT 1
    """, (document_id,)).fetchone()
    if not target:
        conn.close()
        return {"success": False, "code": "NOT_FOUND"}
    if target["lifecycle_status"] != LIFECYCLE_PENDING:
        conn.close()
        return {"success": False, "code": "NOT_AVAILABLE"}

    cursor.execute("""
        UPDATE audit_logs
        SET lifecycle_status = 'LOCKED', assigned_expert = ?
        WHERE document_id = ? AND lifecycle_status = 'PENDING'
    """, (expert_username, document_id))
    rows_updated = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": rows_updated > 0, "document_id": document_id}

def unlock_requirement_set(document_id: str, expert_username: str):
    """Releases an active lock on a document set, returning it back to the pending pool."""
    conn = _connect_pool()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_logs
        SET lifecycle_status = 'PENDING', assigned_expert = NULL
        WHERE document_id = ? AND assigned_expert = ? AND lifecycle_status = 'LOCKED'
    """, (document_id, expert_username))
    rows_updated = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": rows_updated > 0}

def parse_model_output_python(output):
    analysis = output or ""
    rewrite = "No rewrite suggested."
    if output and "### Suggested Rewrite" in output:
        parts = output.split("### Suggested Rewrite")
        analysis = parts[0].replace("### Analysis", "").strip()
        rewrite = parts[1].strip()
    return analysis, rewrite

def submit_expert_review(document_id: str, expert_username: str, reviews: list, is_approved: bool):
    """Finalizes one owned document and exports approved four-field records once."""
    existing_records = _load_training_records() if is_approved else []
    existing_hashes = {_record_hash(record) for record in existing_records}
    conn = _connect_pool()
    try:
        row = conn.execute("""
            SELECT username, document_name, lifecycle_status, assigned_expert
            FROM audit_logs WHERE document_id = ? LIMIT 1
        """, (document_id,)).fetchone()
        if not row:
            return {"success": False, "code": "NOT_FOUND"}

        target_status = LIFECYCLE_APPROVED if is_approved else LIFECYCLE_REJECTED
        if row["lifecycle_status"] == target_status and row["assigned_expert"] == expert_username:
            conn.close()
            if is_approved:
                _process_pending_exports(document_id)
            return {"success": True, "already_processed": True, "status": target_status}
        if row["lifecycle_status"] != LIFECYCLE_LOCKED or row["assigned_expert"] != expert_username:
            return {"success": False, "code": "NOT_LOCK_OWNER"}

        database_rows = conn.execute("""
            SELECT id, requirement, matched_rule, model_output
            FROM audit_logs
            WHERE document_id = ? AND lifecycle_status = 'LOCKED'
              AND assigned_expert = ?
            ORDER BY id
        """, (document_id, expert_username)).fetchall()
        review_by_id = {review["id"]: review for review in reviews}
        expected_ids = {database_row["id"] for database_row in database_rows}
        if set(review_by_id) != expected_ids:
            return {"success": False, "code": "REVIEW_SET_MISMATCH"}

        any_changes = False
        updated_rows = []
        for database_row in database_rows:
            review = review_by_id[database_row["id"]]
            expert_eval = review["expert_evaluation"].strip()
            expert_rew = review["expert_rewrite"].strip()
            ai_eval, ai_rew = parse_model_output_python(database_row["model_output"])
            if expert_eval != ai_eval.strip() or expert_rew != ai_rew.strip():
                any_changes = True

            cursor = conn.execute("""
                UPDATE audit_logs
                SET expert_evaluation = ?, expert_rewrite = ?, lifecycle_status = ?
                WHERE id = ? AND document_id = ? AND assigned_expert = ?
                  AND lifecycle_status = 'LOCKED'
            """, (
                expert_eval,
                expert_rew,
                target_status,
                database_row["id"],
                document_id,
                expert_username,
            ))
            if cursor.rowcount != 1:
                raise RuntimeError("A requirement changed ownership during submission.")
            updated_rows.append({
                "id": database_row["id"],
                "requirement": database_row["requirement"],
                "matched_rule": database_row["matched_rule"],
                "expert_evaluation": expert_eval,
                "expert_rewrite": expert_rew,
            })

        if is_approved:
            _register_export_rows(conn, updated_rows, existing_hashes)

        if any_changes and is_approved:
            conn.execute("""
                INSERT INTO notifications (
                    username, document_id, document_name, expert_username, message
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                row["username"],
                document_id,
                row["document_name"],
                expert_username,
                f"Expert {expert_username} completed auditing '{row['document_name']}' and published improvements.",
            ))

        conn.commit()
        if is_approved:
            _process_pending_exports(document_id)
        return {"success": True, "status": target_status}
    except Exception as exc:
        conn.rollback()
        print(f"Error submitting expert review: {exc}")
        return {"success": False, "code": "SUBMISSION_FAILED", "detail": str(exc)}
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

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
        WHERE document_id = ? AND username = ? AND lifecycle_status = 'APPROVED'
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
        WHERE lifecycle_status = 'APPROVED' AND assigned_expert = ?
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
    """Returns internal records grouped by the canonical lifecycle status."""
    conn = _connect_pool()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.id, a.timestamp, a.requirement, a.matched_rule, a.model_output,
               a.username, a.lifecycle_status, a.assigned_expert,
               a.expert_evaluation, a.expert_rewrite, a.document_id,
               a.document_name, t.export_status
        FROM audit_logs a
        LEFT JOIN training_exports t ON t.audit_log_id = a.id
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    grouped = {"pending": [], "locked": [], "approved": [], "rejected": []}
    for row in rows:
        item = {
            "id": row[0],
            "timestamp": row[1],
            "requirement": row[2],
            "matched_rule": row[3],
            "model_output": row[4],
            "username": row[5],
            "lifecycle_status": row[6],
            "assigned_expert": row[7] or "",
            "expert_evaluation": row[8] or "",
            "expert_rewrite": row[9] or "",
            "document_id": row[10],
            "document_name": row[11] or "Untitled",
            "export_status": row[12] or "NOT_APPLICABLE",
        }
        grouped[row[6].lower()].append(item)
    return grouped
