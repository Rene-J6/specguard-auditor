import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import database


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_auth_path = database.AUTH_DB_PATH
        self.original_pool_path = database.SQLITE_DB_PATH
        database.AUTH_DB_PATH = str(root / "auth.db")
        database.SQLITE_DB_PATH = str(root / "training_pool.db")
        database.init_sqlite_pool()

    def tearDown(self):
        database.AUTH_DB_PATH = self.original_auth_path
        database.SQLITE_DB_PATH = self.original_pool_path
        self.temp_dir.cleanup()

    def create_user(self, username, role="User", email=None):
        success, message = database.create_user_account(
            username=username,
            password="password123",
            full_name=f"{username} Name",
            email=email or f"{username}@example.com",
            role=role,
        )
        self.assertTrue(success, message)
        return database.get_user_by_username(username)

    def test_auth_migration_preserves_hash_and_creates_backup(self):
        old_hash = generate_password_hash(
            "legacy-password", method="pbkdf2:sha256:10000"
        )
        conn = sqlite3.connect(database.AUTH_DB_PATH)
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                role TEXT DEFAULT 'User',
                phone_number TEXT,
                company_name TEXT
            )
        """)
        conn.execute(
            """INSERT INTO users
               (username, password_hash, full_name, email, role)
               VALUES (?, ?, ?, ?, ?)""",
            ("legacy", old_hash, "Legacy User", "legacy@example.com", "Admin"),
        )
        conn.commit()
        conn.close()

        database.init_auth_db()

        conn = sqlite3.connect(database.AUTH_DB_PATH)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            stored_hash, active = conn.execute(
                "SELECT password_hash, is_active FROM users WHERE username = 'legacy'"
            ).fetchone()
            version = conn.execute(
                "SELECT MAX(version) FROM auth_schema_migrations"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(stored_hash, old_hash)
        self.assertEqual(active, 1)
        self.assertEqual(version, 1)
        self.assertTrue({"is_active", "created_at", "updated_at", "last_login_at"} <= columns)
        self.assertTrue(Path(database.auth_backup_path()).exists())

    def test_public_registration_is_user_and_email_login_is_canonical(self):
        database.init_auth_db()
        success, message = database.register_user(
            "CaseUser",
            "password123",
            "Case User",
            "CaseUser@example.com",
        )
        self.assertTrue(success, message)

        user = database.authenticate_user("caseuser@EXAMPLE.com", "password123")

        self.assertEqual(user["username"], "CaseUser")
        self.assertEqual(user["role"], "User")
        self.assertTrue(user["is_active"])
        self.assertTrue(user["password_hash"].startswith("pbkdf2:sha256:10000$"))

    def test_session_uses_hash_and_logout_revokes_it(self):
        database.init_auth_db()
        user = self.create_user("user1")

        token = database.create_session(user["id"])
        session_user = database.get_session_user(token)

        self.assertEqual(session_user["username"], "user1")
        conn = sqlite3.connect(database.AUTH_DB_PATH)
        stored = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        conn.close()
        self.assertNotEqual(stored, token)

        database.revoke_session(token)
        self.assertIsNone(database.get_session_user(token))

    def test_admin_cannot_disable_self_or_last_admin(self):
        database.init_auth_db()
        admin = self.create_user("admin", "Admin")

        self_disable = database.update_managed_user(
            actor_user_id=admin["id"], target_user_id=admin["id"], is_active=False
        )
        last_admin = database.update_managed_user(
            actor_user_id=999, target_user_id=admin["id"], role="User"
        )

        self.assertEqual(self_disable["code"], "CANNOT_DISABLE_SELF")
        self.assertEqual(last_admin["code"], "LAST_ACTIVE_ADMIN")

    def test_active_lock_blocks_expert_role_or_status_change(self):
        database.init_auth_db()
        admin = self.create_user("admin", "Admin")
        expert = self.create_user("expert", "Expert")
        database.log_audit_to_db(
            "submitter",
            "The system shall store records.",
            "standard.pdf | Rule",
            "### Analysis\nIssue\n### Suggested Rewrite\nRewrite",
            "doc_locked",
            "locked.pdf",
        )
        database.lock_requirement_set("doc_locked", "expert")

        result = database.update_managed_user(
            actor_user_id=admin["id"], target_user_id=expert["id"], role="User"
        )

        self.assertEqual(result["code"], "ACTIVE_EXPERT_LOCK")
        self.assertEqual(result["document_id"], "doc_locked")

    def test_activity_statistics_count_distinct_documents(self):
        database.init_auth_db()
        self.create_user("submitter")
        expert = self.create_user("expert", "Expert")
        for index in range(2):
            database.log_audit_to_db(
                "submitter", f"Requirement {index}", "Rule", "Output",
                "doc_one", "one.pdf"
            )
        database.log_audit_to_db(
            "submitter", "Requirement 3", "Rule", "Output", "doc_two", "two.pdf"
        )
        database.lock_requirement_set("doc_one", "expert")
        reviews = [
            {
                "id": row["id"],
                "expert_evaluation": "Evaluation",
                "expert_rewrite": "Rewrite",
            }
            for row in database.fetch_document_requirements("doc_one", "expert")["requirements"]
        ]
        database.submit_expert_review("doc_one", "expert", reviews, False)

        users = {row["username"]: row for row in database.list_managed_users()}

        self.assertEqual(users["submitter"]["submitted_document_count"], 2)
        self.assertEqual(users["expert"]["reviewed_document_count"], 1)
        self.assertEqual(users["expert"]["id"], expert["id"])

    def test_security_dependency_rejects_missing_session_and_wrong_role(self):
        from fastapi import HTTPException
        from app import security

        database.init_auth_db()
        user = self.create_user("user1")
        token = database.create_session(user["id"])

        resolved = security.get_current_user(token)
        self.assertEqual(resolved["username"], "user1")
        with self.assertRaises(HTTPException) as missing:
            security.get_current_user(None)
        self.assertEqual(missing.exception.status_code, 401)
        with self.assertRaises(HTTPException) as forbidden:
            security.ensure_role(resolved, "Admin")
        self.assertEqual(forbidden.exception.status_code, 403)

    def test_public_and_workflow_schemas_reject_caller_roles_and_usernames(self):
        from pydantic import ValidationError
        from app.api_schemas import AnalysisRequest, LockRequest, RegisterRequest

        with self.assertRaises(ValidationError):
            RegisterRequest(
                username="newuser",
                password="password123",
                full_name="New User",
                email="new@example.com",
                role="Expert",
            )
        with self.assertRaises(ValidationError):
            AnalysisRequest(username="forged", raw_text="Text")
        with self.assertRaises(ValidationError):
            LockRequest(document_id="doc1", expert_username="forged")

    def test_notification_mutations_require_owner(self):
        conn = sqlite3.connect(database.SQLITE_DB_PATH)
        cursor = conn.execute("""
            INSERT INTO notifications (
                username, document_id, document_name, expert_username, message
            ) VALUES ('owner', 'doc1', 'one.pdf', 'expert', 'Updated')
        """)
        notification_id = cursor.lastrowid
        conn.commit()
        conn.close()

        self.assertFalse(database.mark_notification_as_read(notification_id, "other"))
        self.assertFalse(database.delete_notification(notification_id, "other"))
        self.assertTrue(database.mark_notification_as_read(notification_id, "owner"))
        self.assertTrue(database.delete_notification(notification_id, "owner"))

    def test_admin_bootstrap_only_runs_without_active_admin(self):
        database.init_auth_db()
        created, message = database.bootstrap_admin(
            "firstadmin", "password123", "First Admin", "first@example.com"
        )
        blocked, blocked_message = database.bootstrap_admin(
            "secondadmin", "password123", "Second Admin", "second@example.com"
        )

        self.assertTrue(created, message)
        self.assertFalse(blocked)
        self.assertIn("already exists", blocked_message)

    def test_status_change_and_password_change_revoke_sessions(self):
        database.init_auth_db()
        admin = self.create_user("admin", "Admin")
        user = self.create_user("user1")
        first_token = database.create_session(user["id"])

        disabled = database.update_managed_user(
            actor_user_id=admin["id"], target_user_id=user["id"], is_active=False
        )

        self.assertTrue(disabled["success"])
        self.assertIsNone(database.get_session_user(first_token))

        database.update_managed_user(
            actor_user_id=admin["id"], target_user_id=user["id"], is_active=True
        )
        second_token = database.create_session(user["id"])
        changed = database.change_user_password(
            user["id"], "password123", "newpassword123"
        )
        authenticated = database.authenticate_user("user1", "newpassword123")

        self.assertTrue(changed["success"])
        self.assertIsNone(database.get_session_user(second_token))
        self.assertTrue(authenticated["password_hash"].startswith("pbkdf2:sha256:10000$"))

    def test_username_and_email_are_unique_without_case_sensitivity(self):
        database.init_auth_db()
        self.create_user("CaseUser", email="case@example.com")

        duplicate_username, _ = database.create_user_account(
            "caseuser", "password123", "Duplicate", "other@example.com"
        )
        duplicate_email, _ = database.create_user_account(
            "otheruser", "password123", "Duplicate", "CASE@example.com"
        )

        self.assertFalse(duplicate_username)
        self.assertFalse(duplicate_email)


if __name__ == "__main__":
    unittest.main()
