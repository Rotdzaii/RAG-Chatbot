"""Retire notifications while preserving manual URL ingestion and deployed schema."""
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4
import unittest

from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select

import test_source_activation as activation_fixture
from main import app
from rag.models import Chunk, Document, SourceChangeNotification
from rag.url_sources import FetchedSource, SourceFetchError


class URLNotificationRetirementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = activation_fixture.SourceActivationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.sessions = self.fixture.sessions
        self.url = "https://www.vlu.edu.vn/isolated-retired-notifications"

    def upload(self):
        with patch("rag.admin_router.fetch_source", return_value=FetchedSource(
            self.url, "fixture.txt", "text/plain", b"original fixture",
        )):
            response = self.client.post("/admin/knowledge-sources/url", json={
                "url": self.url, "category": " policy ", "audience": " staff ",
            })
        self.assertEqual(response.status_code, 201, response.text)
        return UUID(response.json()["document_id"])

    def save_legacy_notification(self, source_id):
        with self.sessions() as session:
            document = session.get(Document, source_id)
            document.is_active = False
            legacy = SourceChangeNotification(
                document_id=source_id, baseline_hash=document.content_hash,
                observed_hash=sha256(b"historical observation").hexdigest(),
            )
            session.add(legacy)
            session.commit()
            return legacy.id

    def test_retired_notification_endpoints_are_absent_without_database_access(self):
        paths = app.openapi()["paths"]
        self.assertNotIn("/admin/source-change-notifications", paths)
        self.assertNotIn("/admin/source-change-notifications/{notification_id}/read", paths)
        with patch("rag.admin_router.SessionLocal") as sessions:
            self.assertEqual(self.client.get("/admin/source-change-notifications").status_code, 404)
            self.assertEqual(self.client.post(f"/admin/source-change-notifications/{uuid4()}/read").status_code, 404)
            sessions.assert_not_called()

    def test_url_import_and_manual_refresh_preserve_metadata_activation_and_legacy_rows(self):
        source_id = self.upload()
        legacy_id = self.save_legacy_notification(source_id)
        self.fixture.embed.reset_mock()
        for content, expected in ((b"changed fixture", "updated"), (b"changed fixture", "unchanged")):
            with patch("rag.admin_router.fetch_source", return_value=FetchedSource(
                self.url, "fixture.txt", "text/plain", content,
            )) as fetch:
                response = self.client.post(f"/admin/knowledge-sources/{source_id}/refresh")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], expected)
            self.assertEqual(response.json()["document_id"], str(source_id))
            fetch.assert_called_once_with(self.url)
            with self.sessions() as session:
                source = session.get(Document, source_id)
                self.assertEqual((source.category, source.audience, source.is_active), ("policy", "staff", False))
                self.assertEqual(source.content_hash, sha256(content).hexdigest())
                self.assertIsNotNone(source.last_checked_at)
                self.assertEqual(session.scalar(select(Chunk.content).where(Chunk.document_id == source_id)), "changed fixture")
                legacy = session.get(SourceChangeNotification, legacy_id)
                self.assertEqual(legacy.baseline_hash, sha256(b"original fixture").hexdigest())
                self.assertEqual(legacy.observed_hash, sha256(b"historical observation").hexdigest())
                self.assertIsNone(legacy.read_at)
                self.assertEqual(session.scalar(select(func.count(SourceChangeNotification.id))), 1)
        self.fixture.embed.assert_called_once()
        # The legacy relationship still performs its normal cleanup on source deletion.
        self.assertEqual(self.client.delete(f"/admin/knowledge-sources/{source_id}").status_code, 204)
        with self.sessions() as session:
            self.assertIsNone(session.get(SourceChangeNotification, legacy_id))

    def test_failed_refresh_preserves_corpus_and_historical_notifications(self):
        source_id = self.upload()
        legacy_id = self.save_legacy_notification(source_id)
        with self.sessions() as session:
            previous = session.get(Document, source_id)
            before = (previous.content_hash, previous.updated_at, previous.last_checked_at)
            chunk_ids = session.scalars(select(Chunk.id).where(Chunk.document_id == source_id)).all()
        self.fixture.embed.reset_mock()
        with patch("rag.admin_router.fetch_source", side_effect=SourceFetchError("Source is unavailable")):
            response = self.client.post(f"/admin/knowledge-sources/{source_id}/refresh")
        self.assertEqual(response.status_code, 502)
        self.fixture.embed.assert_not_called()
        with self.sessions() as session:
            current = session.get(Document, source_id)
            self.assertEqual((current.content_hash, current.updated_at, current.last_checked_at), before)
            self.assertEqual(session.scalars(select(Chunk.id).where(Chunk.document_id == source_id)).all(), chunk_ids)
            self.assertIsNotNone(session.get(SourceChangeNotification, legacy_id))

    def test_url_mutations_still_require_admin_before_fetch_or_database_access(self):
        self.fixture.as_user(uuid4())
        with patch("rag.admin_router.fetch_source") as fetch, patch("rag.admin_router.SessionLocal") as sessions:
            self.assertEqual(self.client.post("/admin/knowledge-sources/url", json={"url": self.url}).status_code, 403)
            self.assertEqual(self.client.post(f"/admin/knowledge-sources/{uuid4()}/refresh").status_code, 403)
            fetch.assert_not_called()
            sessions.assert_not_called()

    def test_legacy_schema_and_applied_migration_chain_are_retained(self):
        graph = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations"))
        self.assertEqual(graph.get_heads(), ["a7e3c9d1b502"])
        self.assertEqual(graph.get_revision("f9d4b2c7e501").down_revision, "b6c8d0e2f4a1")
        self.assertEqual(graph.get_revision("c2a1e8d4f6b0").down_revision, "f9d4b2c7e501")
        inspector = inspect(self.fixture.engine)
        self.assertIn("source_change_notifications", inspector.get_table_names())
        self.assertIn("uq_source_change_notification_transition", {
            constraint["name"] for constraint in inspector.get_unique_constraints("source_change_notifications")
        })


if __name__ == "__main__":
    unittest.main()
