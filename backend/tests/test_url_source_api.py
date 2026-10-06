import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import require_admin  # noqa: E402
from rag.admin_router import URLSourceRequest, router, upload_url_source  # noqa: E402
from rag.url_sources import FetchedSource, SourceFetchError  # noqa: E402


class URLSourceAPITests(unittest.TestCase):
    def test_admin_dependency_is_attached_to_url_route(self) -> None:
        route = next(
            route
            for route in router.routes
            if getattr(route, "path", None) == "/admin/knowledge-sources/url"
        )
        self.assertIn("POST", route.methods)
        self.assertIn(require_admin, [item.call for item in route.dependant.dependencies])

    def test_rejects_bad_url_without_network_or_database(self) -> None:
        with (
            patch("rag.admin_router.SessionLocal") as session_local,
            patch("rag.admin_router.fetch_source") as fetch,
        ):
            with self.assertRaises(HTTPException) as raised:
                upload_url_source(URLSourceRequest(url="http://127.0.0.1/admin"))
        self.assertEqual(raised.exception.status_code, 400)
        session_local.assert_not_called()
        fetch.assert_not_called()

    def test_existing_url_skips_fetch_and_embedding(self) -> None:
        lookup = Mock()
        lookup.scalar.return_value = uuid4()
        with (
            patch("rag.admin_router.SessionLocal", return_value=lookup),
            patch("rag.admin_router.fetch_source") as fetch,
            patch("rag.admin_router.ingest_document") as ingest,
        ):
            with self.assertRaises(HTTPException) as raised:
                upload_url_source(URLSourceRequest(url="https://www.vlu.edu.vn/page"))
        self.assertEqual(raised.exception.status_code, 409)
        fetch.assert_not_called()
        ingest.assert_not_called()
        lookup.close.assert_called_once_with()

    def test_ingests_url_and_preserves_source_metadata(self) -> None:
        lookup = Mock()
        lookup.scalar.return_value = None
        writing = Mock()
        content = b"<p>Marketing at VLU</p>"
        fetched = FetchedSource(
            url="https://www.vlu.edu.vn/page",
            filename="page.html",
            mime_type="text/html",
            content=content,
        )
        document = SimpleNamespace(
            id=uuid4(), filename="page.html", chunks=[object()]
        )
        with (
            patch("rag.admin_router.SessionLocal", side_effect=[lookup, writing]),
            patch("rag.admin_router.fetch_source", return_value=fetched) as fetch,
            patch("rag.admin_router.ingest_document", return_value=document) as ingest,
        ):
            response = upload_url_source(URLSourceRequest(url=fetched.url))
        self.assertEqual(
            response,
            {"document_id": str(document.id), "filename": "page.html", "chunk_count": 1},
        )
        fetch.assert_called_once_with(fetched.url)
        ingest.assert_called_once_with(
            writing, "page.html", "text/html", content, source_url=fetched.url
        )
        lookup.close.assert_called_once_with()
        writing.close.assert_called_once_with()

    def test_fetch_failure_does_not_open_ingestion_session(self) -> None:
        lookup = Mock()
        lookup.scalar.return_value = None
        with (
            patch("rag.admin_router.SessionLocal", return_value=lookup) as session_local,
            patch("rag.admin_router.fetch_source", side_effect=SourceFetchError("Source is unavailable")),
            patch("rag.admin_router.ingest_document") as ingest,
        ):
            with self.assertRaises(HTTPException) as raised:
                upload_url_source(URLSourceRequest(url="https://www.vlu.edu.vn/page"))
        self.assertEqual(raised.exception.status_code, 502)
        session_local.assert_called_once_with()
        ingest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
