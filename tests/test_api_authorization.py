import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


fake_torch = types.ModuleType("torch")
fake_torch.__file__ = str(Path(tempfile.gettempdir()) / "torch.py")
inserted_fake_torch = "torch" not in sys.modules
sys.modules.setdefault("torch", fake_torch)

fake_engine = types.ModuleType("app.model_engine")
fake_engine.load_pipeline_resources = lambda: (None, None, None, None)
inserted_fake_engine = "app.model_engine" not in sys.modules
sys.modules.setdefault("app.model_engine", fake_engine)

from app import database
from app.main import app


class ApiAuthorizationTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        if inserted_fake_torch and sys.modules.get("torch") is fake_torch:
            sys.modules.pop("torch")
        if inserted_fake_engine and sys.modules.get("app.model_engine") is fake_engine:
            sys.modules.pop("app.model_engine")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_auth_path = database.AUTH_DB_PATH
        self.original_pool_path = database.SQLITE_DB_PATH
        self.original_dataset_path = database.EXPORT_JSONL_PATH
        database.AUTH_DB_PATH = str(root / "auth.db")
        database.SQLITE_DB_PATH = str(root / "training_pool.db")
        database.EXPORT_JSONL_PATH = str(root / "dataset.jsonl")
        Path(database.EXPORT_JSONL_PATH).write_text(
            json.dumps({
                "bad_requirement": "Seed",
                "document_reference": "Rule",
                "analysis": "Analysis",
                "suggested_rewrite": "Rewrite",
            }) + "\n",
            encoding="utf-8",
        )
        database.init_auth_db()
        database.init_sqlite_pool()
        database.create_user_account(
            "user1", "password123", "User One", "user1@example.com", "User"
        )
        database.create_user_account(
            "expert1", "password123", "Expert One", "expert1@example.com", "Expert"
        )
        database.create_user_account(
            "admin1", "password123", "Admin One", "admin1@example.com", "Admin"
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        database.AUTH_DB_PATH = self.original_auth_path
        database.SQLITE_DB_PATH = self.original_pool_path
        database.EXPORT_JSONL_PATH = self.original_dataset_path
        self.temp_dir.cleanup()

    def login(self, username):
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "password123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_user_session_cannot_access_admin_api(self):
        response = self.login("user1")

        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/history").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/api/expert/queue").status_code, 403)

    def test_admin_can_list_users_and_public_registration_rejects_role(self):
        self.login("admin1")
        users = self.client.get("/api/admin/users")

        self.assertEqual(users.status_code, 200)
        self.assertEqual(len(users.json()), 3)
        rejected = self.client.post(
            "/api/auth/register",
            json={
                "username": "forged",
                "password": "password123",
                "full_name": "Forged Expert",
                "email": "forged@example.com",
                "role": "Expert",
            },
        )
        self.assertEqual(rejected.status_code, 422)

    def test_email_login_returns_canonical_username(self):
        response = self.login("USER1@example.com")

        self.assertEqual(response.json()["username"], "user1")
        self.assertEqual(self.client.get("/api/auth/me").json()["role"], "User")


if __name__ == "__main__":
    unittest.main()
