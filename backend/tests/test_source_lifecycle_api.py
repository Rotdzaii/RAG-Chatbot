import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException, UploadFile


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import require_admin  # noqa: E402
from rag.admin_router import (  # noqa: E402
    delete_knowledge_source, refresh_url_source, replace_file_source, router,
)
from rag.source_lifecycle import ReplacementResult, SourceChanged  # noqa: E402
from rag.url_sources import FetchedSource, SourceFetchError  # noqa: E402


class SourceLifecycleAPITests(unittest.TestCase):
    def test_mutations_require_admin(self):
        for path, method in (
            ("/admin/knowledge-sources/{source_id}/refresh", "POST"),
            ("/admin/knowledge-sources/{source_id}/file", "PUT"),
            ("/admin/knowledge-sources/{source_id}", "DELETE"),
        ):
            route = next(route for route in router.routes if route.path == path)
            self.assertIn(method, route.methods)
            self.assertIn(require_admin, [dependency.call for dependency in route.dependant.dependencies])

    def test_refresh_fetches_stored_url_and_replaces_same_document(self):
        source_id = uuid4()
        url = "https://www.vlu.edu.vn/page"
        lookup = Mock()
        lookup.scalar.return_value = SimpleNamespace(source_type="url", source_url=url)
        writing = Mock()
        fetched = FetchedSource(url, "page.html", "text/html", b"updated")
        result = ReplacementResult(source_id, "page.html", 2, "updated")
        with (
            patch("rag.admin_router.SessionLocal", side_effect=[lookup, writing]),
            patch("rag.admin_router.fetch_source", return_value=fetched) as fetch,
            patch("rag.admin_router.replace_source", return_value=result) as replace,
        ):
            response = refresh_url_source(source_id)
        self.assertEqual(response.model_dump(), {
            "document_id": source_id, "filename": "page.html", "chunk_count": 2, "status": "updated",
        })
        fetch.assert_called_once_with(url)
        replace.assert_called_once_with(
            writing, source_id, source_type="url", filename="page.html",
            mime_type="text/html", content=b"updated", source_url=url,
        )
        lookup.close.assert_called_once()
        writing.close.assert_called_once()

    def test_fetch_failure_does_not_open_writing_session(self):
        source_id = uuid4()
        lookup = Mock()
        lookup.scalar.return_value = SimpleNamespace(
            source_type="url", source_url="https://www.vlu.edu.vn/page"
        )
        with (
            patch("rag.admin_router.SessionLocal", return_value=lookup) as sessions,
            patch("rag.admin_router.fetch_source", side_effect=SourceFetchError("unavailable")),
            patch("rag.admin_router.replace_source") as replace,
        ):
            with self.assertRaises(HTTPException) as raised:
                refresh_url_source(source_id)
        self.assertEqual(raised.exception.status_code, 502)
        sessions.assert_called_once_with()
        replace.assert_not_called()

    def test_file_replacement_limits_and_conflict(self):
        from io import BytesIO

        source_id = uuid4()
        file = UploadFile(file=BytesIO(b"new"), filename="new.txt", headers={
            "content-type": "text/plain"
        })
        session = Mock()
        with (
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch("rag.admin_router.replace_source", side_effect=SourceChanged()) as replace,
        ):
            with self.assertRaises(HTTPException) as raised:
                replace_file_source(source_id, file)
        self.assertEqual(raised.exception.status_code, 409)
        replace.assert_called_once_with(
            session, source_id, source_type="file", filename="new.txt",
            mime_type="text/plain", content=b"new",
        )
        session.close.assert_called_once()

        empty = UploadFile(file=BytesIO(b""), filename="empty.txt", headers={
            "content-type": "text/plain"
        })
        with patch("rag.admin_router.SessionLocal") as sessions:
            with self.assertRaises(HTTPException) as raised:
                replace_file_source(source_id, empty)
        self.assertEqual(raised.exception.status_code, 400)
        sessions.assert_not_called()

    def test_delete_reports_missing_and_closes_session(self):
        source_id = uuid4()
        session = Mock()
        with (
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch("rag.admin_router.delete_source", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                delete_knowledge_source(source_id)
        self.assertEqual(raised.exception.status_code, 404)
        session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
