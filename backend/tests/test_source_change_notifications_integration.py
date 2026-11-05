"""Real transactions and the new migration in temporary SQLite, with fake URLs."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
import runpy
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://offline:offline@localhost/offline")
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, require_admin  # noqa: E402
from main import app  # noqa: E402
from rag.models import Document, SourceChangeNotification  # noqa: E402
from rag.source_change_checks import check_url_source  # noqa: E402
from rag.url_sources import FetchedSource, SourceFetchError  # noqa: E402


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations/versions/f9d4b2c7e501_add_source_change_notifications.py"


class SourceChangeNotificationIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(directory.name) / 'isolated.db'}", connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def functions(connection, _record):
            connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
            connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat())
            connection.execute("PRAGMA foreign_keys=ON")

        Document.__table__.create(self.engine)
        self.migration = runpy.run_path(str(MIGRATION))
        self.apply_migration("upgrade")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.source_id = uuid4()
        self.url = "https://www.vlu.edu.vn/isolated-fixture"
        self.baseline = sha256(b"original fixture").hexdigest()
        with self.sessions() as session:
            session.add(Document(
                id=self.source_id, filename="fixture.html", mime_type="text/html",
                source_type="url", source_url=self.url, content_hash=self.baseline,
                embedding_profile="unchanged-embedding", chunking_profile="unchanged-chunking",
            ))
            session.commit()
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(uuid4())
        self.client = TestClient(app)

    def apply_migration(self, direction):
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                self.migration[direction]()

    def check(self, content):
        with self.sessions() as session, patch("rag.source_change_checks.fetch_source", return_value=FetchedSource(
            self.url, "fixture.html", "text/html", content,
        )):
            return check_url_source(session, self.source_id)

    def count(self):
        with self.sessions() as session:
            return session.scalar(select(func.count(SourceChangeNotification.id)))

    def test_change_deduplicates_even_after_read_and_keeps_corpus_baseline(self):
        self.assertEqual(self.check(b"original fixture").status, "unchanged")
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.check(b"changed fixture").status, "changed")
        self.assertEqual(self.check(b"changed fixture").status, "already_notified")
        self.assertEqual(self.count(), 1)
        with patch("rag.admin_router.SessionLocal", self.sessions):
            listed = self.client.get("/admin/source-change-notifications?unread_only=true")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()), 1)
            alert = listed.json()[0]
            self.assertEqual(alert["source_url"], self.url)
            self.assertEqual(alert["baseline_hash"], self.baseline)
            self.assertEqual(alert["observed_hash"], sha256(b"changed fixture").hexdigest())
            path = f"/admin/source-change-notifications/{alert['id']}/read"
            first = self.client.post(path)
            second = self.client.post(path)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertIsNotNone(first.json()["read_at"])
            # SQLite drops the timezone on reload; PostgreSQL keeps timestamptz.
            self.assertEqual(
                datetime.fromisoformat(first.json()["read_at"]).replace(tzinfo=timezone.utc),
                datetime.fromisoformat(second.json()["read_at"]).replace(tzinfo=timezone.utc),
            )
            self.assertEqual(self.client.get("/admin/source-change-notifications?unread_only=true").json(), [])
            self.assertEqual(len(self.client.get("/admin/source-change-notifications").json()), 1)
            self.assertEqual(self.client.post(f"/admin/source-change-notifications/{uuid4()}/read").status_code, 404)
        self.assertEqual(self.check(b"changed fixture").status, "already_notified")
        self.assertEqual(self.check(b"another changed fixture").status, "changed")
        self.assertEqual(self.count(), 2)
        with self.sessions() as session:
            source = session.get(Document, self.source_id)
            self.assertEqual(source.content_hash, self.baseline)
            self.assertEqual(source.embedding_profile, "unchanged-embedding")
            self.assertEqual(source.chunking_profile, "unchanged-chunking")
            self.assertIsNotNone(source.last_checked_at)

    def test_database_unique_constraint_and_cascade_are_real(self):
        self.assertEqual(self.check(b"changed fixture").status, "changed")
        with self.sessions() as session:
            session.add(SourceChangeNotification(
                document_id=self.source_id, baseline_hash=self.baseline,
                observed_hash=sha256(b"changed fixture").hexdigest(),
            ))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
        self.assertEqual(self.count(), 1)
        with self.sessions() as session:
            session.execute(delete(Document).where(Document.id == self.source_id))
            session.commit()
        self.assertEqual(self.count(), 0)

    def test_refresh_during_fetch_is_stale_without_notification(self):
        replacement_hash = sha256(b"admin refreshed fixture").hexdigest()

        def fetch(_url):
            with self.sessions() as updating:
                updating.get(Document, self.source_id).content_hash = replacement_hash
                updating.commit()
            return FetchedSource(self.url, "fixture.html", "text/html", b"observed fixture")

        with self.sessions() as session, patch("rag.source_change_checks.fetch_source", side_effect=fetch):
            self.assertEqual(check_url_source(session, self.source_id).status, "stale")
        self.assertEqual(self.count(), 0)
        with self.sessions() as session:
            self.assertEqual(session.get(Document, self.source_id).content_hash, replacement_hash)
            self.assertIsNone(session.get(Document, self.source_id).last_checked_at)

    def test_missing_baseline_and_fetch_failure_do_not_write(self):
        with self.sessions() as session, patch("rag.source_change_checks.fetch_source", side_effect=SourceFetchError("private fixture detail")):
            self.assertEqual(check_url_source(session, self.source_id).status, "fetch_error")
        with self.sessions() as session:
            source = session.get(Document, self.source_id)
            self.assertIsNone(source.last_checked_at)
            source.content_hash = None
            session.commit()
        with self.sessions() as session, patch("rag.source_change_checks.fetch_source") as fetch:
            self.assertEqual(check_url_source(session, self.source_id).status, "unknown_baseline")
            fetch.assert_not_called()
        self.assertEqual(self.count(), 0)

    def test_manual_cli_uses_isolated_database_fake_urls_and_failure_exit_status(self):
        cli = runpy.run_path(str(BACKEND.parent / "scripts/check_url_source_changes.py"))["main"]
        fetched = FetchedSource(self.url, "fixture.html", "text/html", b"changed fixture")
        with patch("database.SessionLocal", self.sessions), patch("rag.source_change_checks.fetch_source", return_value=fetched):
            for expected in ("changed", "already_notified"):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli([]), 0)
                self.assertIn(expected, output.getvalue())
                self.assertIn("checked=1 failures=0", output.getvalue())
        self.assertEqual(self.count(), 1)
        output = StringIO()
        with patch("database.SessionLocal", self.sessions), patch("rag.source_change_checks.fetch_source", side_effect=SourceFetchError("private fixture detail")), redirect_stdout(output):
            self.assertEqual(cli([]), 1)
        self.assertIn("checked=1 failures=1", output.getvalue())
        self.assertNotIn("private fixture detail", output.getvalue())
        self.assertEqual(self.count(), 1)

    def test_new_migration_creates_constraint_index_and_can_downgrade_in_isolation(self):
        inspector = inspect(self.engine)
        self.assertIn("source_change_notifications", inspector.get_table_names())
        self.assertIn("uq_source_change_notification_transition", {
            constraint["name"] for constraint in inspector.get_unique_constraints("source_change_notifications")
        })
        self.assertIn("ix_source_change_notifications_read_at", {
            index["name"] for index in inspector.get_indexes("source_change_notifications")
        })
        self.apply_migration("downgrade")
        self.assertNotIn("source_change_notifications", inspect(self.engine).get_table_names())
        self.assertIn("documents", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
