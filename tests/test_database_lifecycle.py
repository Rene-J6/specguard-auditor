import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import database


class DatabaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_db_path = database.SQLITE_DB_PATH
        self.original_dataset_path = database.EXPORT_JSONL_PATH
        database.SQLITE_DB_PATH = str(root / "training_pool.db")
        database.EXPORT_JSONL_PATH = str(root / "dataset.jsonl")
        Path(database.EXPORT_JSONL_PATH).write_text(
            json.dumps({
                "bad_requirement": "Synthetic requirement",
                "document_reference": "Synthetic rule",
                "analysis": "Synthetic analysis",
                "suggested_rewrite": "Synthetic rewrite",
            }) + "\n",
            encoding="utf-8",
        )
        database.init_sqlite_pool()

    def tearDown(self):
        database.SQLITE_DB_PATH = self.original_db_path
        database.EXPORT_JSONL_PATH = self.original_dataset_path
        self.temp_dir.cleanup()

    def add_document(self, document_id, requirement_count=2):
        for index in range(requirement_count):
            database.log_audit_to_db(
                "user1",
                f"The system shall process item {index}.",
                f"standard.pdf | Rule {index}",
                f"### Analysis\nAI analysis {index}\n\n### Suggested Rewrite\nAI rewrite {index}",
                document_id,
                f"{document_id}.pdf",
            )

    def reviews_for(self, document_id, expert="expert1"):
        result = database.fetch_document_requirements(document_id, expert)
        self.assertTrue(result["success"])
        return [
            {
                "id": row["id"],
                "expert_evaluation": f"Verified analysis {row['id']}",
                "expert_rewrite": f"Verified rewrite {row['id']}",
            }
            for row in result["requirements"]
        ]

    def dataset_records(self):
        return [
            json.loads(line)
            for line in Path(database.EXPORT_JSONL_PATH).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_single_active_lock_and_ownership(self):
        self.add_document("doc_one")
        self.add_document("doc_two")

        first = database.lock_requirement_set("doc_one", "expert1")
        self.assertTrue(first["success"])
        repeated = database.lock_requirement_set("doc_one", "expert1")
        self.assertTrue(repeated["success"])
        self.assertTrue(repeated["already_locked"])

        second = database.lock_requirement_set("doc_two", "expert1")
        self.assertFalse(second["success"])
        self.assertEqual(second["code"], "ACTIVE_LOCK_EXISTS")
        other_expert = database.lock_requirement_set("doc_one", "expert2")
        self.assertFalse(other_expert["success"])
        self.assertEqual(other_expert["code"], "NOT_AVAILABLE")
        forbidden = database.fetch_document_requirements("doc_one", "expert2")
        self.assertEqual(forbidden["code"], "FORBIDDEN")

        self.assertTrue(database.unlock_requirement_set("doc_one", "expert1")["success"])
        self.assertTrue(database.lock_requirement_set("doc_two", "expert1")["success"])

    def test_approve_exports_once_and_admin_delete_revokes(self):
        self.add_document("doc_approved")
        database.lock_requirement_set("doc_approved", "expert1")
        reviews = self.reviews_for("doc_approved")

        approved = database.submit_expert_review(
            "doc_approved", "expert1", reviews, True
        )
        self.assertTrue(approved["success"])
        self.assertEqual(len(self.dataset_records()), 3)
        for record in self.dataset_records():
            self.assertEqual(set(record), set(database.TRAINING_FIELDS))

        repeated = database.submit_expert_review(
            "doc_approved", "expert1", reviews, True
        )
        self.assertTrue(repeated["already_processed"])
        self.assertEqual(len(self.dataset_records()), 3)

        conn = sqlite3.connect(database.SQLITE_DB_PATH)
        requirement_id = conn.execute(
            "SELECT id FROM audit_logs WHERE document_id = ? ORDER BY id LIMIT 1",
            ("doc_approved",),
        ).fetchone()[0]
        conn.close()
        deleted = database.delete_log_entry(requirement_id)
        self.assertTrue(deleted["success"])
        self.assertEqual(len(self.dataset_records()), 2)

        deleted_document = database.delete_document_entry("doc_approved")
        self.assertTrue(deleted_document["success"])
        self.assertEqual(len(self.dataset_records()), 1)

    def test_reject_is_retained_and_not_exported(self):
        self.add_document("doc_rejected")
        database.lock_requirement_set("doc_rejected", "expert1")
        before_count = len(self.dataset_records())
        rejected = database.submit_expert_review(
            "doc_rejected", "expert1", self.reviews_for("doc_rejected"), False
        )
        self.assertTrue(rejected["success"])
        self.assertEqual(len(self.dataset_records()), before_count)

        conn = sqlite3.connect(database.SQLITE_DB_PATH)
        statuses = conn.execute(
            "SELECT DISTINCT lifecycle_status FROM audit_logs WHERE document_id = ?",
            ("doc_rejected",),
        ).fetchall()
        conn.close()
        self.assertEqual(statuses, [(database.LIFECYCLE_REJECTED,)])

    def test_user_history_hides_internal_lifecycle(self):
        self.add_document("doc_history", requirement_count=1)
        columns = set(database.fetch_user_history("user1").columns)
        self.assertNotIn("lifecycle_status", columns)
        self.assertNotIn("assigned_expert", columns)
        self.assertNotIn("export_status", columns)


class LegacyMigrationTests(unittest.TestCase):
    def test_migration_maps_states_and_reduces_multiple_expert_locks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_db_path = database.SQLITE_DB_PATH
            old_dataset_path = database.EXPORT_JSONL_PATH
            try:
                database.SQLITE_DB_PATH = str(root / "training_pool.db")
                database.EXPORT_JSONL_PATH = str(root / "dataset.jsonl")
                Path(database.EXPORT_JSONL_PATH).write_text("", encoding="utf-8")
                conn = sqlite3.connect(database.SQLITE_DB_PATH)
                conn.execute("""
                    CREATE TABLE audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        requirement TEXT, matched_rule TEXT, model_output TEXT,
                        status TEXT DEFAULT 'Pending', is_validated INTEGER DEFAULT 0,
                        username TEXT, document_id TEXT, document_name TEXT,
                        review_status TEXT DEFAULT 'Pending', assigned_expert TEXT,
                        expert_evaluation TEXT, expert_rewrite TEXT
                    )
                """)
                rows = [
                    ("Pending req", "rule", "out", "Pending", 0, "u", "pending", "p.pdf", "Pending", None, None, None),
                    ("Old lock", "rule", "out", "Pending", 0, "u", "old_lock", "old.pdf", "Locked", "expert", None, None),
                    ("New lock", "rule", "out", "Pending", 0, "u", "new_lock", "new.pdf", "Locked", "expert", None, None),
                    ("Approved req", "rule", "out", "Validated", 1, "u", "approved", "a.pdf", "Approved", "expert", "analysis", "rewrite"),
                ]
                conn.executemany("""
                    INSERT INTO audit_logs (
                        requirement, matched_rule, model_output, status, is_validated,
                        username, document_id, document_name, review_status,
                        assigned_expert, expert_evaluation, expert_rewrite
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)
                conn.execute(
                    "UPDATE audit_logs SET timestamp = '2024-01-01' WHERE document_id = 'old_lock'"
                )
                conn.execute(
                    "UPDATE audit_logs SET timestamp = '2025-01-01' WHERE document_id = 'new_lock'"
                )
                conn.commit()
                conn.close()

                database.init_sqlite_pool()
                conn = sqlite3.connect(database.SQLITE_DB_PATH)
                states = dict(conn.execute(
                    "SELECT document_id, lifecycle_status FROM audit_logs"
                ).fetchall())
                conn.close()
                self.assertEqual(states["pending"], database.LIFECYCLE_PENDING)
                self.assertEqual(states["old_lock"], database.LIFECYCLE_PENDING)
                self.assertEqual(states["new_lock"], database.LIFECYCLE_LOCKED)
                self.assertEqual(states["approved"], database.LIFECYCLE_APPROVED)
                self.assertTrue((root / "training_pool.pre_lifecycle_v2.backup.db").exists())
                self.assertEqual(len([
                    line for line in Path(database.EXPORT_JSONL_PATH).read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]), 1)
            finally:
                database.SQLITE_DB_PATH = old_db_path
                database.EXPORT_JSONL_PATH = old_dataset_path


if __name__ == "__main__":
    unittest.main()
