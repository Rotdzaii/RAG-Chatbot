from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import UniqueConstraint


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user, require_admin  # noqa: E402
from main import app  # noqa: E402
from rag.admin_router import (  # noqa: E402
    list_source_change_notifications, mark_source_change_notification_read,
    router,
)
from rag.models import SourceChangeNotification  # noqa: E402
from rag.source_change_checks import check_url_source  # noqa: E402
from rag.url_sources import FetchedSource, SourceFetchError  # noqa: E402


class SourceChangeCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_id = uuid4()
        self.url = "https://www.vlu.edu.vn/page"
        self.old = b"old page"
        self.baseline = sha256(self.old).hexdigest()

    def _session(
        self, content: bytes, *, rowcount: int = 1,
        initial_hash: str | None = "default", current_hash: str | None = "default",
    ) -> Mock:
        source = SimpleNamespace(
            id=self.source_id, source_type="url", source_url=self.url,
            content_hash=self.baseline if initial_hash == "default" else initial_hash,
            last_checked_at=None,
        )
        current = SimpleNamespace(
            id=self.source_id, source_type="url", source_url=self.url,
            content_hash=self.baseline if current_hash == "default" else current_hash,
            last_checked_at=None,
        )
        session = Mock()
        session.scalar.side_effect = [source, current]
        session.execute.return_value.rowcount = rowcount
        return session

    def test_unchanged_url_does_not_notify(self) -> None:
        session = self._session(self.old)
        with patch("rag.source_change_checks.fetch_source", return_value=FetchedSource(
            self.url, "page.html", "text/html", self.old,
        )):
            result = check_url_source(session, self.source_id)
        self.assertEqual(result.status, "unchanged")
        session.execute.assert_not_called()
        session.commit.assert_called_once()

    def test_database_enforces_transition_deduplication(self) -> None:
        table = SourceChangeNotification.__table__
        unique = next(
            item for item in table.constraints
            if isinstance(item, UniqueConstraint)
            and item.name == "uq_source_change_notification_transition"
        )
        self.assertEqual(
            tuple(column.name for column in unique.columns),
            ("document_id", "baseline_hash", "observed_hash"),
        )
        self.assertFalse(table.c.baseline_hash.nullable)
        self.assertFalse(table.c.observed_hash.nullable)

    def test_changed_url_notifies_once_for_same_transition(self) -> None:
        changed = b"new page"
        fetched = FetchedSource(self.url, "page.html", "text/html", changed)
        with patch("rag.source_change_checks.fetch_source", return_value=fetched):
            first = check_url_source(self._session(changed), self.source_id)
            duplicate_session = self._session(changed, rowcount=0)
            duplicate = check_url_source(duplicate_session, self.source_id)
        self.assertEqual(first.status, "changed")
        self.assertEqual(duplicate.status, "already_notified")
        statement = duplicate_session.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertIn("ON CONFLICT", str(compiled))
        self.assertIn(self.baseline, compiled.params.values())
        self.assertIn(sha256(changed).hexdigest(), compiled.params.values())

    def test_fetch_error_does_not_write_or_change_baseline(self) -> None:
        session = self._session(b"ignored")
        with patch("rag.source_change_checks.fetch_source", side_effect=SourceFetchError("unavailable")):
            result = check_url_source(session, self.source_id)
        self.assertEqual(result.status, "fetch_error")
        session.execute.assert_not_called()
        session.commit.assert_not_called()

    def test_missing_baseline_is_not_called_change(self) -> None:
        session = self._session(b"ignored", initial_hash=None)
        with patch("rag.source_change_checks.fetch_source") as fetch:
            result = check_url_source(session, self.source_id)
        self.assertEqual(result.status, "unknown_baseline")
        fetch.assert_not_called()

    def test_refresh_race_is_not_compared_to_old_baseline(self) -> None:
        session = self._session(b"new", current_hash="f" * 64)
        with patch("rag.source_change_checks.fetch_source", return_value=FetchedSource(
            self.url, "page.html", "text/html", b"new",
        )):
            result = check_url_source(session, self.source_id)
        self.assertEqual(result.status, "stale")
        session.execute.assert_not_called()


class SourceChangeNotificationAPITests(unittest.TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_routes_require_admin_and_reject_nonadmin(self) -> None:
        paths = {
            "/admin/source-change-notifications": "GET",
            "/admin/source-change-notifications/{notification_id}/read": "POST",
        }
        for path, method in paths.items():
            route = next(route for route in router.routes if route.path == path)
            self.assertIn(method, route.methods)
            self.assertIn(require_admin, [d.call for d in route.dependant.dependencies])

        client = TestClient(app)
        self.assertEqual(client.get("/admin/source-change-notifications").status_code, 401)
        self.assertEqual(
            client.post(f"/admin/source-change-notifications/{uuid4()}/read").status_code, 401
        )
        admin_id = uuid4()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(uuid4())
        with patch("config.settings", SimpleNamespace(admin_user_id=admin_id)):
            self.assertEqual(client.get("/admin/source-change-notifications").status_code, 403)
            self.assertEqual(
                client.post(f"/admin/source-change-notifications/{uuid4()}/read").status_code, 403
            )

    def test_admin_can_list_and_mark_read_idempotently(self) -> None:
        document_id, notification_id = uuid4(), uuid4()
        created = datetime(2026, 10, 14, tzinfo=timezone.utc)
        alert = SimpleNamespace(
            id=notification_id, document_id=document_id,
            baseline_hash="a" * 64, observed_hash="b" * 64,
            detected_at=created, read_at=None,
        )
        session = Mock()
        session.execute.return_value.all.return_value = [(alert, "https://www.vlu.edu.vn/page")]
        session.scalar.side_effect = [alert, "https://www.vlu.edu.vn/page", alert,
                                      "https://www.vlu.edu.vn/page"]
        with patch("rag.admin_router.SessionLocal", return_value=session):
            listed = list_source_change_notifications(unread_only=True, limit=20, offset=0)
            first = mark_source_change_notification_read(notification_id)
            second = mark_source_change_notification_read(notification_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].source_url, "https://www.vlu.edu.vn/page")
        self.assertIsNotNone(first.read_at)
        self.assertEqual(second.read_at, first.read_at)
        session.commit.assert_called_once()

    def test_admin_http_endpoints(self) -> None:
        notification_id, document_id = uuid4(), uuid4()
        alert = SimpleNamespace(
            id=notification_id, document_id=document_id,
            baseline_hash="a" * 64, observed_hash="b" * 64,
            detected_at=datetime(2026, 10, 14, tzinfo=timezone.utc), read_at=None,
        )
        session = Mock()
        session.execute.return_value.all.return_value = [(alert, "https://www.vlu.edu.vn/page")]
        session.scalar.side_effect = [alert, "https://www.vlu.edu.vn/page"]
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(uuid4())
        with patch("rag.admin_router.SessionLocal", return_value=session):
            client = TestClient(app)
            listed = client.get("/admin/source-change-notifications?unread_only=true")
            marked = client.post(f"/admin/source-change-notifications/{notification_id}/read")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], str(notification_id))
        self.assertEqual(marked.status_code, 200)
        self.assertIsNotNone(marked.json()["read_at"])


class SourceChangeCLITests(unittest.TestCase):
    def test_notification_revision_extends_single_current_head(self) -> None:
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        graph = ScriptDirectory(str(migration_dir))
        self.assertEqual(graph.get_heads(), ["a7e3c9d1b502"])
        self.assertEqual(graph.get_revision("c2a1e8d4f6b0").down_revision, "f9d4b2c7e501")
        self.assertEqual(
            graph.get_revision("f9d4b2c7e501").down_revision,
            "b6c8d0e2f4a1",
        )

    def test_help_and_bad_argument_do_not_initialize_backend(self) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "check_url_source_changes.py"
        # -S removes site packages: any premature SQLAlchemy/Settings import
        # fails before it could open a DB connection or fetch a URL.
        help_result = subprocess.run(
            [sys.executable, "-S", str(script), "--help"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--help", help_result.stdout)
        self.assertIn("Check indexed URL sources", help_result.stdout)

        bad_result = subprocess.run(
            [sys.executable, "-S", str(script), "--not-a-real-option"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(bad_result.returncode, 2, bad_result.stderr)
        self.assertIn("unrecognized arguments", bad_result.stderr)


if __name__ == "__main__":
    unittest.main()
