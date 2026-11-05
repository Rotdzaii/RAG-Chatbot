import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://user:password@localhost/test")
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user, require_admin
from main import app
from rag.source_metadata import RetrievalFilters, SourceMetadataPatch, normalize_metadata
from rag.url_sources import FetchedSource
from test_extraction import create_two_page_pdf
from test_source_lifecycle import existing_source
from rag.source_lifecycle import replace_source
from rag.chunking import TextChunk


class SourceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(uuid4())
        self.client = TestClient(app)
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        storage = patch("rag.source_files.source_file_directory", return_value=Path(self.storage.name))
        storage.start()
        self.addCleanup(storage.stop)

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.overrides)

    def test_normalization_is_explicit_and_case_sensitive_without_taxonomy(self):
        self.assertEqual(normalize_metadata("  ho\u0323c\t vu\u0323 \n"), "học vụ")
        self.assertEqual(normalize_metadata("Policy"), "Policy")
        self.assertIsNone(normalize_metadata(" \t"))
        self.assertEqual(RetrievalFilters(category=" Policy  ").category, "Policy")
        for values in ({"category": " "}, {"audience": 32}, {"effective_from": "2026-01-01"}):
            with self.assertRaises(ValidationError):
                RetrievalFilters(**values)
        self.assertEqual(SourceMetadataPatch(category=None).model_dump(exclude_unset=True), {"category": None})

    def test_patch_is_admin_only_before_database_or_embedding(self):
        app.dependency_overrides.clear()
        with patch("rag.admin_router.SessionLocal") as sessions, patch("rag.embeddings._get_embeddings") as embed:
            self.assertEqual(self.client.patch(f"/admin/knowledge-sources/{uuid4()}/metadata", json={"category": "policy"}).status_code, 401)
            app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(uuid4())
            with patch("config.settings", SimpleNamespace(admin_user_id=uuid4())):
                self.assertEqual(self.client.patch(f"/admin/knowledge-sources/{uuid4()}/metadata", json={"category": "policy"}).status_code, 403)
            sessions.assert_not_called()
            embed.assert_not_called()

    def test_patch_omission_null_and_only_metadata_without_reindex(self):
        for body in ({"category": "  policy  "}, {"audience": None}, {"category": "  "}, {"category": "rules", "audience": " staff "}):
            with self.subTest(body=body):
                source = SimpleNamespace(id=uuid4(), category="old", audience=" legacy audience ", updated_at=datetime.now(timezone.utc))
                session = Mock()
                session.scalar.return_value = source
                with patch("rag.admin_router.SessionLocal", return_value=session), patch("rag.embeddings._get_embeddings") as embed, patch("rag.ingestion._prepare_chunks") as prepare:
                    response = self.client.patch(f"/admin/knowledge-sources/{source.id}/metadata", json=body)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["category"], normalize_metadata(body["category"]) if "category" in body else "old")
                self.assertEqual(response.json()["audience"], normalize_metadata(body["audience"]) if "audience" in body else " legacy audience ")
                embed.assert_not_called()
                prepare.assert_not_called()
                session.execute.assert_not_called()
                session.add.assert_not_called()
                session.commit.assert_called_once()
                session.close.assert_called_once()
                self.assertIsNotNone(session.scalar.call_args.args[0]._for_update_arg)

    def test_patch_rejects_empty_unknown_and_wrong_types_before_session(self):
        with patch("rag.admin_router.SessionLocal") as sessions:
            for body in ({}, {"category": []}, {"audience": 3}, {"effective_to": None}, {"source_url": "https://www.vlu.edu.vn"}, {"category": "ok", "is_active": True}):
                with self.subTest(body=body):
                    self.assertEqual(self.client.patch(f"/admin/knowledge-sources/{uuid4()}/metadata", json=body).status_code, 422)
            sessions.assert_not_called()

    def test_patch_missing_and_commit_failure_are_safe(self):
        session = Mock()
        session.scalar.return_value = None
        with patch("rag.admin_router.SessionLocal", return_value=session):
            self.assertEqual(self.client.patch(f"/admin/knowledge-sources/{uuid4()}/metadata", json={"category": None}).status_code, 404)
        session.commit.assert_not_called()
        session.scalar.return_value = SimpleNamespace(id=uuid4(), category="old", audience=None)
        session.commit.side_effect = SQLAlchemyError("private connection details")
        with patch("rag.admin_router.SessionLocal", return_value=session):
            response = self.client.patch(f"/admin/knowledge-sources/{uuid4()}/metadata", json={"category": "new"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Source metadata update is unavailable"})
        session.rollback.assert_called_once()

    def test_pdf_txt_url_ingestion_persists_normalized_optional_metadata(self):
        for kind in ("pdf", "txt", "url"):
            with self.subTest(kind=kind):
                session, lookup = Mock(), Mock()
                lookup.scalar.return_value = None
                session.add.side_effect = lambda document: setattr(document, "id", uuid4())
                with (
                    patch("rag.router.SessionLocal", return_value=session),
                    patch("rag.admin_router.SessionLocal", side_effect=[lookup, session]),
                    patch("rag.admin_router.fetch_source", return_value=FetchedSource("https://www.vlu.edu.vn/page", "page.html", "text/html", b"<p>Document content</p>")),
                    patch("rag.ingestion.embed_documents", return_value=[[1.0] + [0.0] * 767]),
                ):
                    if kind == "url":
                        response = self.client.post("/admin/knowledge-sources/url", json={"url": "https://www.vlu.edu.vn/page", "category": "  policy ", "audience": " staff  members "})
                    else:
                        content = create_two_page_pdf("First", "Second") if kind == "pdf" else b"Document content"
                        response = self.client.post("/documents", files={"file": (f"new.{kind}", content, "application/pdf" if kind == "pdf" else "text/plain")}, data={"category": "  policy ", "audience": " staff  members "})
                self.assertEqual(response.status_code, 201, response.text)
                document = session.add.call_args.args[0]
                self.assertEqual((document.category, document.audience), ("policy", "staff members"))
                session.commit.assert_called_once()

    def test_list_filters_are_normalized_and_blank_is_not_unfiltered(self):
        session = Mock()
        page = SimpleNamespace(items=[], total=0, limit=20, offset=0)
        with patch("rag.admin_router.SessionLocal", return_value=session), patch("rag.admin_router.list_knowledge_sources", return_value=page) as listing:
            response = self.client.get("/admin/knowledge-sources", params={"category": " policy ", "audience": " staff  members "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(listing.call_args.kwargs["category"], "policy")
        self.assertEqual(listing.call_args.kwargs["audience"], "staff members")
        with patch("rag.admin_router.SessionLocal") as sessions:
            self.assertEqual(self.client.get("/admin/knowledge-sources", params={"category": " "}).status_code, 422)
            sessions.assert_not_called()

    def test_replace_refresh_preserve_legacy_metadata_changed_or_unchanged(self):
        for kind in ("file", "url"):
            for content in (b"old", b"new"):
                with self.subTest(kind=kind, content=content):
                    document = existing_source()
                    document.source_type = kind
                    document.source_url = "https://www.vlu.edu.vn/page" if kind == "url" else None
                    document.category = " legacy category "
                    document.audience = None
                    session = Mock()
                    session.scalar.side_effect = [document, 2, None] if content == b"old" else [document, document]
                    with patch("rag.source_lifecycle._prepare_chunks", return_value=([TextChunk("new", 0, 3)], (), [[1.0] * 768])):
                        replace_source(session, document.id, source_type=kind, filename="guide.txt", mime_type="text/plain", content=content, source_url=document.source_url)
                    self.assertEqual(document.category, " legacy category ")
                    self.assertIsNone(document.audience)


if __name__ == "__main__":
    unittest.main()
