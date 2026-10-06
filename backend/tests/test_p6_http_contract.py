"""Exercise the PDF and URL HTTP boundaries without a DB or provider call."""

import sys
import unittest
from hashlib import sha256
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user, require_admin  # noqa: E402
from main import app  # noqa: E402
from rag.index_provenance import CHUNKING_PROFILE, current_embedding_profile  # noqa: E402
from rag.url_sources import FetchedSource  # noqa: E402
from test_extraction import create_two_page_pdf  # noqa: E402


def mock_write_session() -> Mock:
    session = Mock()

    def commit() -> None:
        document = session.add.call_args.args[0]
        document.id = uuid4()

    session.commit.side_effect = commit
    return session


def fake_embed(texts: list[str]) -> list[list[float]]:
    return [[1.0] + [0.0] * 767 for _ in texts]


class P6HTTPContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(id=uuid4())
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_pdf_upload_records_page_ranges_hash_and_profiles(self) -> None:
        content = create_two_page_pdf("First page", "Second page")
        session = mock_write_session()
        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.ingestion.embed_documents", side_effect=fake_embed) as embed,
        ):
            response = self.client.post(
                "/documents", files={"file": ("guide.pdf", content, "application/pdf")}
            )

        self.assertEqual(response.status_code, 201)
        document = session.add.call_args.args[0]
        self.assertEqual(response.json(), {
            "document_id": str(document.id),
            "filename": "guide.pdf",
            "chunk_count": len(document.chunks),
        })
        self.assertEqual(document.content_hash, sha256(content).hexdigest())
        self.assertEqual(document.embedding_profile, current_embedding_profile())
        self.assertEqual(document.chunking_profile, CHUNKING_PROFILE)
        self.assertEqual(
            [(chunk.page_start, chunk.page_end) for chunk in document.chunks],
            [(1, 2)],
        )
        self.assertIn("First page", document.chunks[0].content)
        self.assertIn("Second page", document.chunks[0].content)
        self.assertEqual(len(document.chunks[0].embedding), 768)
        embed.assert_called_once()
        session.commit.assert_called_once_with()
        session.close.assert_called_once_with()

    def test_url_upload_extracts_html_and_preserves_source_url(self) -> None:
        url = "https://www.vlu.edu.vn/academics/majors/software"
        html = b"<nav>Skip this</nav><h1>Software Engineering</h1><p>Four years</p>"
        lookup = Mock()
        lookup.scalar.return_value = None
        writing = mock_write_session()
        fetched = FetchedSource(url, "software.html", "text/html", html)
        with (
            patch("rag.admin_router.SessionLocal", side_effect=[lookup, writing]),
            patch("rag.admin_router.fetch_source", return_value=fetched) as fetch,
            patch("rag.ingestion.embed_documents", side_effect=fake_embed) as embed,
        ):
            response = self.client.post("/admin/knowledge-sources/url", json={"url": url})

        self.assertEqual(response.status_code, 201)
        document = writing.add.call_args.args[0]
        self.assertEqual(response.json(), {
            "document_id": str(document.id),
            "filename": "software.html",
            "chunk_count": len(document.chunks),
        })
        self.assertEqual(document.source_type, "url")
        self.assertEqual(document.source_url, url)
        self.assertEqual(document.content_hash, sha256(html).hexdigest())
        self.assertEqual([chunk.content for chunk in document.chunks], [
            "Software Engineering\nFour years"
        ])
        self.assertIsNone(document.chunks[0].page_start)
        self.assertIsNone(document.chunks[0].page_end)
        fetch.assert_called_once_with(url)
        embed.assert_called_once()
        lookup.close.assert_called_once_with()
        writing.commit.assert_called_once_with()
        writing.close.assert_called_once_with()

    def test_admin_uploads_require_auth_before_fetch_or_embedding(self) -> None:
        app.dependency_overrides.clear()
        with (
            patch("rag.router.SessionLocal") as pdf_session,
            patch("rag.admin_router.SessionLocal") as url_session,
            patch("rag.admin_router.fetch_source") as fetch,
            patch("rag.ingestion.embed_documents") as embed,
        ):
            pdf = self.client.post(
                "/documents", files={"file": ("guide.pdf", b"%PDF", "application/pdf")}
            )
            url = self.client.post(
                "/admin/knowledge-sources/url",
                json={"url": "https://www.vlu.edu.vn/page"},
            )

        self.assertEqual(pdf.status_code, 401)
        self.assertEqual(url.status_code, 401)
        pdf_session.assert_not_called()
        url_session.assert_not_called()
        fetch.assert_not_called()
        embed.assert_not_called()

    def test_non_admin_cannot_upload_url_or_replace_file(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=uuid4()
        )
        config = ModuleType("config")
        config.settings = SimpleNamespace(admin_user_id=uuid4())
        with (
            patch.dict(sys.modules, {"config": config}),
            patch("rag.admin_router.SessionLocal") as sessions,
            patch("rag.admin_router.fetch_source") as fetch,
            patch("rag.admin_router.replace_source") as replace,
        ):
            url = self.client.post(
                "/admin/knowledge-sources/url",
                json={"url": "https://www.vlu.edu.vn/page"},
            )
            replacement = self.client.put(
                f"/admin/knowledge-sources/{uuid4()}/file",
                files={"file": ("new.txt", b"content", "text/plain")},
            )

        self.assertEqual(url.status_code, 403)
        self.assertEqual(replacement.status_code, 403)
        sessions.assert_not_called()
        fetch.assert_not_called()
        replace.assert_not_called()


if __name__ == "__main__":
    unittest.main()
