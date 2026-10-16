import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


fake_torch = types.ModuleType("torch")
fake_torch.__file__ = str(Path(tempfile.gettempdir()) / "torch.py")
inserted_fake_torch = "torch" not in sys.modules
sys.modules.setdefault("torch", fake_torch)

fake_engine = types.ModuleType("app.model_engine")
fake_engine.load_pipeline_resources = lambda: (None, None, None)
inserted_fake_engine = "app.model_engine" not in sys.modules
sys.modules.setdefault("app.model_engine", fake_engine)

from app import database
from app import main as main_module

app = main_module.app


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
        self.root = root
        self.original_auth_path = database.AUTH_DB_PATH
        self.original_pool_path = database.SQLITE_DB_PATH
        self.original_dataset_path = database.EXPORT_JSONL_PATH
        self.original_temp_path = main_module.TEMP_DIR
        database.AUTH_DB_PATH = str(root / "auth.db")
        database.SQLITE_DB_PATH = str(root / "training_pool.db")
        database.EXPORT_JSONL_PATH = str(root / "dataset.jsonl")
        main_module.TEMP_DIR = str(root / "temp")
        Path(main_module.TEMP_DIR).mkdir()
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
        main_module.TEMP_DIR = self.original_temp_path
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

    def test_upload_accepts_pdf_signature_and_uses_safe_temporary_path(self):
        self.login("user1")
        text = "The system shall preserve every approved audit record. " * 2
        with patch("app.main.extract_text_from_pdf", return_value=text) as extractor:
            response = self.client.post(
                "/api/analysis/upload",
                files={"file": ("../../escape.pdf", b"%PDF-1.4 sample", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        temp_path = Path(extractor.call_args.args[0])
        self.assertEqual(temp_path.parent, self.root / "temp")
        self.assertFalse(temp_path.exists())

    def test_upload_rejects_image_mime_extension_and_spoofed_signature(self):
        self.login("user1")
        cases = [
            ("scan.png", b"\x89PNG", "image/png"),
            ("notes.pdf", b"%PDF-1.4", "text/plain"),
            ("fake.pdf", b"not a pdf", "application/pdf"),
        ]
        for filename, content, content_type in cases:
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/api/analysis/upload",
                    files={"file": (filename, content, content_type)},
                )
                self.assertEqual(response.status_code, 415, response.text)

    def test_upload_distinguishes_corrupt_and_textless_pdfs(self):
        self.login("user1")
        errors = [
            (main_module.InvalidPdfError("Invalid or corrupted PDF."), 400),
            (main_module.NoExtractableTextError(
                "Only digital PDFs with extractable text are supported."
            ), 422),
        ]
        for error, expected_status in errors:
            with self.subTest(status=expected_status), patch(
                "app.main.extract_text_from_pdf", side_effect=error
            ):
                response = self.client.post(
                    "/api/analysis/upload",
                    files={"file": ("sample.pdf", b"%PDF-1.4 sample", "application/pdf")},
                )
                self.assertEqual(response.status_code, expected_status, response.text)

    def test_audit_stream_adds_validated_structure_and_stores_json(self):
        self.login("user1")
        requirement = "The system shall return results quickly."
        evidence_text = "Requirements shall use measurable effectiveness criteria."
        candidate = {
            "standard": "ISO/IEC/IEEE 29148:2018",
            "clause": "5.2.5",
            "title": "Characteristics of individual requirements",
            "source": "ISO IEC IEEE 29148.pdf",
            "text": evidence_text,
        }
        generated = json.dumps({
            "compliance_status": "non_compliant",
            "issue_types": ["not_measurable"],
            "evidence_id": "E1",
            "evidence": evidence_text,
            "explanation": "The word quickly has no measurable target.",
            "suggested_rewrite": "The system shall return results within two seconds.",
        })
        with (
            patch.object(main_module, "model", object()),
            patch.object(main_module, "tokenizer", object()),
            patch.object(main_module, "db", object()),
            patch.object(main_module, "segment_document", return_value=[requirement]),
            patch.object(
                main_module.requirement_detector,
                "predict_many",
                return_value=[{"text": requirement, "is_requirement": True}],
            ),
            patch.object(
                main_module,
                "retrieve_standard_evidence",
                return_value={"selected_clause": candidate},
            ),
            patch.object(main_module, "_generate_audit_text", return_value=generated),
        ):
            response = self.client.post(
                "/api/analysis/run",
                json={"raw_text": requirement, "document_name": "sample.pdf"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        chunk = json.loads(response.text.strip())
        self.assertEqual(chunk["data"]["analysis"], chunk["data"]["audit"]["explanation"])
        self.assertEqual(chunk["data"]["audit"]["compliance_status"], "non_compliant")
        rows = database.fetch_user_history("user1")
        stored = json.loads(rows.iloc[0]["model_output"])
        self.assertEqual(stored["schema_version"], 1)
        self.assertEqual(stored["validation_status"], "validated")


if __name__ == "__main__":
    unittest.main()
