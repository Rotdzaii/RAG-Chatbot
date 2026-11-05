import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://user:password@localhost/test")
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user  # noqa: E402
from main import app  # noqa: E402
from rag.models import Chunk, SourceFileVersion  # noqa: E402
from rag.source_files import read_version, store_version  # noqa: E402


class SourceFileAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        storage_patch = patch("rag.source_files.source_file_directory", return_value=Path(self.storage.name))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.previous_overrides = app.dependency_overrides.copy()
        self.user_id = uuid4()
        self.admin_id = uuid4()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(self.user_id)
        self.addCleanup(self._restore_overrides)
        self.client = TestClient(app)

    def _restore_overrides(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def _version(self, content: bytes, mime_type: str = "application/pdf") -> SourceFileVersion:
        version = SourceFileVersion(
            id=uuid4(), document_id=uuid4(), mime_type=mime_type,
            content_hash=sha256(content).hexdigest(), byte_size=len(content),
        )
        store_version(version.id, mime_type, content)
        return version

    def test_legacy_chunks_can_have_no_file_version(self) -> None:
        self.assertTrue(Chunk.__table__.c.source_file_version_id.nullable)

    def test_owner_can_open_exact_pdf_version_with_private_response(self) -> None:
        version = self._version(b"%PDF-old")
        session = Mock()
        session.get.return_value = version
        session.scalar.return_value = uuid4()
        with patch("rag.source_file_router.SessionLocal", return_value=session):
            response = self.client.get(f"/source-files/{version.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-old")
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(str(Path(self.storage.name)), str(response.headers))
        ownership_query = session.scalar.call_args.args[0]
        self.assertIn("conversations.user_id", str(ownership_query))
        self.assertIn("messages.citations @>", str(ownership_query))
        self.assertIn(
            [{"source_file_version_id": str(version.id), "document_id": str(version.document_id)}],
            list(ownership_query.compile().params.values()),
        )

    def test_txt_download_and_replaced_version_remain_distinct(self) -> None:
        old = self._version(b"old text", "text/plain")
        new = self._version(b"new text", "text/plain")
        session = Mock()
        session.get.side_effect = lambda _model, version_id: old if version_id == old.id else new
        session.scalar.return_value = uuid4()
        with patch("rag.source_file_router.SessionLocal", return_value=session):
            first = self.client.get(f"/source-files/{old.id}")
            second = self.client.get(f"/source-files/{new.id}")
        self.assertEqual((first.content, second.content), (b"old text", b"new text"))
        self.assertIn("source.txt", first.headers["content-disposition"])

    def test_admin_can_open_version_without_conversation_citation(self) -> None:
        version = self._version(b"%PDF-admin")
        session = Mock()
        session.get.return_value = version
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(self.admin_id)
        with (
            patch("rag.source_file_router.SessionLocal", return_value=session),
            patch("rag.source_file_router.settings.admin_user_id", self.admin_id, create=True),
        ):
            response = self.client.get(f"/source-files/{version.id}")
        self.assertEqual(response.status_code, 200)
        session.scalar.assert_not_called()

    def test_other_user_and_missing_version_are_not_disclosed(self) -> None:
        version = self._version(b"%PDF-private")
        session = Mock()
        session.get.return_value = version
        session.scalar.return_value = None
        with patch("rag.source_file_router.SessionLocal", return_value=session):
            response = self.client.get(f"/source-files/{version.id}")
        self.assertEqual(response.status_code, 404)
        session.get.return_value = None
        with patch("rag.source_file_router.SessionLocal", return_value=session):
            response = self.client.get(f"/source-files/{uuid4()}")
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_request_never_opens_storage_or_database(self) -> None:
        app.dependency_overrides.pop(get_authenticated_user)
        with patch("rag.source_file_router.SessionLocal") as session_local:
            response = self.client.get(f"/source-files/{uuid4()}")
        self.assertEqual(response.status_code, 401)
        session_local.assert_not_called()

    def test_missing_or_corrupt_bytes_fail_without_serving_content(self) -> None:
        version = self._version(b"original")
        path = Path(self.storage.name) / f"{version.id.hex}.pdf"
        path.write_bytes(b"tampered")
        session = Mock()
        session.get.return_value = version
        session.scalar.return_value = uuid4()
        with patch("rag.source_file_router.SessionLocal", return_value=session):
            response = self.client.get(f"/source-files/{version.id}")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"tampered", response.content)
        self.assertRaises(OSError, read_version, version.id, version.mime_type,
                          version.content_hash, version.byte_size)

    def test_failed_write_removes_temporary_and_does_not_create_version(self) -> None:
        version_id = uuid4()
        with patch("rag.source_files.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store_version(version_id, "text/plain", b"partial")
        self.assertEqual(list(Path(self.storage.name).iterdir()), [])

    def test_existing_version_id_never_overwrites_immutable_bytes(self) -> None:
        version = self._version(b"original bytes", "text/plain")
        with self.assertRaises(FileExistsError):
            store_version(version.id, version.mime_type, b"replacement bytes")
        self.assertEqual(read_version(version.id, version.mime_type, version.content_hash, version.byte_size), b"original bytes")
        self.assertEqual(len(list(Path(self.storage.name).iterdir())), 1)

    def test_missing_file_returns_safe_error_without_internal_storage_path(self) -> None:
        version = self._version(b"original bytes", "text/plain")
        (Path(self.storage.name) / f"{version.id.hex}.txt").unlink()
        session = Mock()
        session.get.return_value = version
        session.scalar.return_value = uuid4()
        with patch("rag.source_file_router.SessionLocal", return_value=session):
            response = self.client.get(f"/source-files/{version.id}")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Source file is unavailable"})
        self.assertNotIn(str(Path(self.storage.name)), response.text)


if __name__ == "__main__":
    unittest.main()
