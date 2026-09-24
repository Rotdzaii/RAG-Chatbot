from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from main import app  # noqa: E402
from rag.knowledge_sources import (  # noqa: E402
    KnowledgeSourcePage,
    KnowledgeSourceRecord,
)


def source_record(filename: str, chunk_count: int) -> KnowledgeSourceRecord:
    timestamp = datetime(2026, 9, 24, 8, 30, tzinfo=timezone.utc)
    return KnowledgeSourceRecord(
        id=uuid4(),
        filename=filename,
        mime_type="text/plain",
        source_type="url",
        source_url="https://example.invalid/policy",
        category="policy",
        audience="students",
        content_hash="b" * 64,
        published_at=timestamp,
        last_checked_at=timestamp,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        created_at=timestamp,
        updated_at=timestamp,
        chunk_count=chunk_count,
    )


class KnowledgeSourceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_returns_empty_page_and_closes_session(self) -> None:
        session = Mock()
        page = KnowledgeSourcePage(items=[], total=0, limit=20, offset=0)

        with (
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch(
                "rag.admin_router.list_knowledge_sources", return_value=page
            ) as list_sources,
        ):
            response = self.client.get("/admin/knowledge-sources")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"items": [], "total": 0, "limit": 20, "offset": 0}
        )
        list_sources.assert_called_once_with(
            session,
            source_type=None,
            category=None,
            audience=None,
            limit=20,
            offset=0,
        )
        session.close.assert_called_once_with()

    def test_returns_metadata_only_in_service_order(self) -> None:
        session = Mock()
        first = source_record("newer.txt", 5)
        second = source_record("older.txt", 2)
        page = KnowledgeSourcePage(
            items=[first, second], total=12, limit=2, offset=4
        )

        with (
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch("rag.admin_router.list_knowledge_sources", return_value=page),
        ):
            response = self.client.get(
                "/admin/knowledge-sources",
                params={
                    "source_type": "url",
                    "category": "policy",
                    "audience": "students",
                    "limit": 2,
                    "offset": 4,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 12)
        self.assertEqual(body["limit"], 2)
        self.assertEqual(body["offset"], 4)
        self.assertEqual(
            [item["filename"] for item in body["items"]],
            ["newer.txt", "older.txt"],
        )
        self.assertEqual(
            [item["chunk_count"] for item in body["items"]], [5, 2]
        )
        for item in body["items"]:
            self.assertNotIn("content", item)
            self.assertNotIn("embedding", item)
        session.close.assert_called_once_with()

    def test_forwards_all_filters(self) -> None:
        session = Mock()
        page = KnowledgeSourcePage(items=[], total=0, limit=8, offset=6)

        with (
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch(
                "rag.admin_router.list_knowledge_sources", return_value=page
            ) as list_sources,
        ):
            response = self.client.get(
                "/admin/knowledge-sources",
                params={
                    "source_type": "file",
                    "category": "rules",
                    "audience": "staff",
                    "limit": 8,
                    "offset": 6,
                },
            )

        self.assertEqual(response.status_code, 200)
        list_sources.assert_called_once_with(
            session,
            source_type="file",
            category="rules",
            audience="staff",
            limit=8,
            offset=6,
        )
        session.close.assert_called_once_with()

    def test_rejects_invalid_parameters_before_session_creation(self) -> None:
        invalid_queries = (
            "?source_type=website",
            "?limit=0",
            "?limit=101",
            "?offset=-1",
        )

        with patch("rag.admin_router.SessionLocal") as session_local:
            responses = [
                self.client.get(f"/admin/knowledge-sources{query}")
                for query in invalid_queries
            ]

        self.assertTrue(all(response.status_code == 422 for response in responses))
        session_local.assert_not_called()

    def test_maps_database_failure_and_closes_session(self) -> None:
        session = Mock()

        with (
            patch("rag.admin_router.SessionLocal", return_value=session),
            patch(
                "rag.admin_router.list_knowledge_sources",
                side_effect=SQLAlchemyError("sensitive database detail"),
            ),
        ):
            response = self.client.get("/admin/knowledge-sources")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Knowledge sources are unavailable"}
        )
        self.assertNotIn("sensitive database detail", response.text)
        session.close.assert_called_once_with()

    def test_existing_routes_remain_registered(self) -> None:
        paths = app.openapi()["paths"]

        for path, method in (
            ("/health", "GET"),
            ("/health/db", "GET"),
            ("/documents", "POST"),
            ("/questions", "POST"),
            ("/admin/knowledge-sources", "GET"),
        ):
            self.assertIn(path, paths)
            self.assertIn(method.lower(), paths[path])


if __name__ == "__main__":
    unittest.main()
