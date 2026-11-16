from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.knowledge_sources import (  # noqa: E402
    KnowledgeSourceRecord,
    get_knowledge_source,
    list_knowledge_sources,
)
from rag.models import Chunk, Document  # noqa: E402


def source_row(filename: str, chunk_count: int) -> dict[str, object]:
    timestamp = datetime(2026, 9, 24, 8, 30, tzinfo=timezone.utc)
    return {
        "id": uuid4(),
        "is_active": True,
        "filename": filename,
        "mime_type": "application/pdf",
        "source_type": "file",
        "source_url": None,
        "category": "policy",
        "audience": "students",
        "content_hash": "a" * 64,
        "published_at": timestamp,
        "last_checked_at": timestamp,
        "effective_from": date(2026, 1, 1),
        "effective_to": date(2026, 12, 31),
        "created_at": timestamp,
        "updated_at": timestamp,
        "chunk_count": chunk_count,
    }


class KnowledgeSourceServiceTests(unittest.TestCase):
    def test_gets_one_source_with_chunk_count(self) -> None:
        session = Mock()
        row = source_row("handbook.pdf", 6)
        session.execute.return_value.mappings.return_value.one_or_none.return_value = row

        result = get_knowledge_source(session, row["id"])

        self.assertIsInstance(result, KnowledgeSourceRecord)
        self.assertEqual(result.id, row["id"])
        self.assertEqual(result.filename, "handbook.pdf")
        self.assertEqual(result.chunk_count, 6)
        session.execute.assert_called_once()

        statement = session.execute.call_args.args[0]
        statement_sql = str(statement)
        self.assertIn("documents.id =", statement_sql)
        self.assertIn("count(chunks.id)", statement_sql)
        self.assertNotIn("chunks.content", statement_sql)
        self.assertNotIn("chunks.embedding", statement_sql)

    def test_get_returns_none_when_source_does_not_exist(self) -> None:
        session = Mock()
        session.execute.return_value.mappings.return_value.one_or_none.return_value = None

        result = get_knowledge_source(session, uuid4())

        self.assertIsNone(result)
        session.execute.assert_called_once()

    def test_returns_empty_page(self) -> None:
        session = Mock()
        session.scalar.return_value = 0
        session.execute.return_value.mappings.return_value = []

        page = list_knowledge_sources(session)

        self.assertEqual(page.items, [])
        self.assertEqual(page.total, 0)
        self.assertEqual(page.limit, 20)
        self.assertEqual(page.offset, 0)
        session.scalar.assert_called_once()
        session.execute.assert_called_once()

    def test_maps_ordered_items_and_chunk_counts(self) -> None:
        session = Mock()
        first = source_row("newer.pdf", 4)
        second = source_row("older.pdf", 0)
        session.scalar.return_value = 2
        session.execute.return_value.mappings.return_value = [first, second]

        page = list_knowledge_sources(session, limit=10, offset=5)

        self.assertEqual(page.total, 2)
        self.assertEqual(page.limit, 10)
        self.assertEqual(page.offset, 5)
        self.assertTrue(
            all(isinstance(item, KnowledgeSourceRecord) for item in page.items)
        )
        self.assertEqual(
            [item.filename for item in page.items], ["newer.pdf", "older.pdf"]
        )
        self.assertEqual([item.chunk_count for item in page.items], [4, 0])

        statement = session.execute.call_args.args[0]
        statement_sql = str(statement)
        self.assertIn(
            "ORDER BY documents.created_at DESC, documents.id DESC", statement_sql
        )
        self.assertEqual(statement._limit_clause.value, 10)
        self.assertEqual(statement._offset_clause.value, 5)
        self.assertNotIn("chunks.content", statement_sql)
        self.assertNotIn("chunks.embedding", statement_sql)

    def test_applies_all_filters_to_total_and_page_queries(self) -> None:
        session = Mock()
        session.scalar.return_value = 0
        session.execute.return_value.mappings.return_value = []

        list_knowledge_sources(
            session,
            source_type="url",
            category="regulations",
            audience="faculty",
            limit=7,
            offset=3,
        )

        total_statement = session.scalar.call_args.args[0]
        page_statement = session.execute.call_args.args[0]
        total_compiled = total_statement.compile()
        page_compiled = page_statement.compile()

        for value in ("url", "regulations", "faculty"):
            self.assertIn(value, total_compiled.params.values())
            self.assertIn(value, page_compiled.params.values())

        total_sql = str(total_statement)
        page_sql = str(page_statement)
        for column in (
            "documents.source_type",
            "documents.category",
            "documents.audience",
        ):
            self.assertIn(column, total_sql)
            self.assertIn(column, page_sql)
        self.assertIsNone(total_statement._limit_clause)
        self.assertIsNone(total_statement._offset_clause)
        self.assertEqual(page_statement._limit_clause.value, 7)
        self.assertEqual(page_statement._offset_clause.value, 3)


class KnowledgeSourceFilenameSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Document.__table__.create(self.engine)
        Chunk.__table__.create(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        stamp = datetime(2026, 11, 16, tzinfo=timezone.utc)
        rows = [
            {"id": uuid4(), "filename": f"newer-{index}.pdf", "mime_type": "application/pdf", "source_type": "file", "created_at": stamp + timedelta(minutes=index), "updated_at": stamp, "is_active": True}
            for index in range(25)
        ]
        self.target_id = uuid4()
        rows.extend([
            {"id": self.target_id, "filename": "CTDT_Software_2026.PDF", "mime_type": "application/pdf", "source_type": "file", "created_at": stamp - timedelta(days=1), "updated_at": stamp, "is_active": True, "category": "curriculum", "audience": "students"},
            {"id": uuid4(), "filename": "ctdt_Software_2025.pdf", "mime_type": "application/pdf", "source_type": "file", "created_at": stamp - timedelta(days=2), "updated_at": stamp, "is_active": False, "category": "curriculum", "audience": "students"},
            {"id": uuid4(), "filename": "CTDT_Software_staff.pdf", "mime_type": "application/pdf", "source_type": "file", "created_at": stamp - timedelta(days=3), "updated_at": stamp, "is_active": True, "category": "curriculum", "audience": "staff"},
            {"id": uuid4(), "filename": "CTDT_Software_URL", "mime_type": "text/html", "source_type": "url", "created_at": stamp - timedelta(days=4), "updated_at": stamp, "is_active": True, "category": "curriculum", "audience": "students"},
            {"id": uuid4(), "filename": "Report_100%.pdf", "mime_type": "application/pdf", "source_type": "file", "created_at": stamp, "updated_at": stamp, "is_active": True},
        ])
        # Core inserts avoid PostgreSQL-only UUID/time server defaults in SQLite.
        for row in rows:
            self.session.execute(Document.__table__.insert().values(**row))
        self.session.commit()

    def test_case_insensitive_partial_match_finds_a_later_page_file(self) -> None:
        first = list_knowledge_sources(self.session, limit=20)
        self.assertNotIn(self.target_id, [item.id for item in first.items])
        matching = list_knowledge_sources(self.session, filename="  sOfTwArE_2026  ")
        self.assertEqual(matching.total, 1)
        self.assertEqual([item.id for item in matching.items], [self.target_id])

    def test_combines_all_filters_before_counting_and_pagination(self) -> None:
        filters = dict(filename="software", source_type="file", category="curriculum", audience="students")
        first = list_knowledge_sources(self.session, **filters, limit=1)
        second = list_knowledge_sources(self.session, **filters, limit=1, offset=1)
        self.assertEqual(first.total, 2)
        self.assertEqual(second.total, 2)
        self.assertEqual(len(first.items), 1)
        self.assertEqual(len(second.items), 1)
        self.assertNotEqual(first.items[0].id, second.items[0].id)
        active = list_knowledge_sources(self.session, **filters, is_active=True)
        self.assertEqual(active.total, 1)
        self.assertEqual(active.items[0].id, self.target_id)
        self.assertEqual(list_knowledge_sources(self.session, **filters, is_active=True, offset=1).items, [])
        self.assertEqual(list_knowledge_sources(self.session, filename="software", category="missing").total, 0)

    def test_wildcards_are_literal_and_blank_search_is_unfiltered(self) -> None:
        for query in ("100%", "Report_", "%"):
            with self.subTest(query=query):
                result = list_knowledge_sources(self.session, filename=query)
                self.assertEqual(result.total, 1)
                self.assertEqual(result.items[0].filename, "Report_100%.pdf")
        for query in (None, "", "   "):
            self.assertEqual(list_knowledge_sources(self.session, filename=query).total, 30)
        self.assertEqual(list_knowledge_sources(self.session, filename="_").total, 5)
        self.assertEqual(list_knowledge_sources(self.session, filename="no-match").total, 0)


if __name__ == "__main__":
    unittest.main()
