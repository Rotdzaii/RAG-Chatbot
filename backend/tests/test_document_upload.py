import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from sqlalchemy.exc import SQLAlchemyError


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user, require_admin
from main import app
from rag.router import MAX_FILE_SIZE, upload_document


class DocumentUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(
            id=uuid4()
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_uploads_document(self) -> None:
        session = Mock()
        document_id = uuid4()
        document = SimpleNamespace(
            id=document_id,
            filename="notes.txt",
            chunks=[object(), object()],
        )

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.ingest_document", return_value=document) as ingest,
        ):
            response = self.client.post(
                "/documents",
                files={"file": ("notes.txt", b"content", "text/plain")},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "document_id": str(document_id),
                "filename": "notes.txt",
                "chunk_count": 2,
            },
        )
        ingest.assert_called_once_with(session, "notes.txt", "text/plain", b"content")
        session.close.assert_called_once_with()

    def test_rejects_unsupported_mime_type(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            response = self.client.post(
                "/documents",
                files={"file": ("notes.png", b"content", "image/png")},
            )

        self.assertEqual(response.status_code, 415)
        session_local.assert_not_called()

    def test_rejects_missing_filename(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            response = self.client.post("/documents")

        self.assertEqual(response.status_code, 400)
        session_local.assert_not_called()

    def test_rejects_empty_file(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            response = self.client.post(
                "/documents",
                files={"file": ("empty.txt", b"", "text/plain")},
            )

        self.assertEqual(response.status_code, 400)
        session_local.assert_not_called()

    def test_rejects_oversized_file(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            response = self.client.post(
                "/documents",
                files={
                    "file": (
                        "large.txt",
                        b"x" * (MAX_FILE_SIZE + 1),
                        "text/plain",
                    )
                },
            )

        self.assertEqual(response.status_code, 413)
        session_local.assert_not_called()

    def test_reads_at_most_the_upload_limit(self) -> None:
        session = Mock()
        file_handle = Mock()
        file_handle.read.return_value = b"content"
        upload = UploadFile(
            file=file_handle,
            filename="notes.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        document = SimpleNamespace(
            id=uuid4(), filename="notes.txt", chunks=[object()]
        )

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.ingest_document", return_value=document),
        ):
            upload_document(upload)

        file_handle.read.assert_called_once_with(MAX_FILE_SIZE + 1)

    def test_maps_validation_errors_to_bad_request(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.ingest_document", side_effect=ValueError("invalid text")),
        ):
            response = self.client.post(
                "/documents",
                files={"file": ("notes.txt", b"content", "text/plain")},
            )

        self.assertEqual(response.status_code, 400)
        session.close.assert_called_once_with()

    def test_maps_database_errors_to_generic_service_unavailable(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.ingest_document",
                side_effect=SQLAlchemyError("internal database detail"),
            ),
        ):
            response = self.client.post(
                "/documents",
                files={"file": ("notes.txt", b"content", "text/plain")},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Database unavailable"})
        session.close.assert_called_once_with()


class DocumentUploadAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_missing_token_denies_upload_before_endpoint_work(self) -> None:
        with (
            patch("tempfile.SpooledTemporaryFile.read") as file_read,
            patch("rag.router.SessionLocal") as session_local,
            patch("rag.router.ingest_document") as ingest,
        ):
            response = self.client.post(
                "/documents",
                files={"file": ("notes.txt", b"content", "text/plain")},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication required"})
        file_read.assert_not_called()
        session_local.assert_not_called()
        ingest.assert_not_called()

    def test_authenticated_non_admin_is_denied_before_endpoint_work(self) -> None:
        admin_id = uuid4()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=uuid4()
        )
        configured = ModuleType("config")
        configured.settings = SimpleNamespace(admin_user_id=admin_id)

        with (
            patch.dict(sys.modules, {"config": configured}),
            patch("tempfile.SpooledTemporaryFile.read") as file_read,
            patch("rag.router.SessionLocal") as session_local,
            patch("rag.router.ingest_document") as ingest,
        ):
            response = self.client.post(
                "/documents",
                files={"file": ("notes.txt", b"content", "text/plain")},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Admin access required"})
        file_read.assert_not_called()
        session_local.assert_not_called()
        ingest.assert_not_called()

    def test_questions_require_authentication(self) -> None:
        with (
            patch("rag.router.SessionLocal") as session_local,
            patch("rag.router.answer_question") as answer,
        ):
            response = self.client.post(
                "/questions", json={"question": "Protected question"}
            )

        self.assertEqual(response.status_code, 401)
        session_local.assert_not_called()
        answer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
