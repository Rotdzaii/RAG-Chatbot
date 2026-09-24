from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.knowledge_sources import (  # noqa: E402
    KnowledgeSourceRecord,
    list_knowledge_sources,
)


def source_row(filename: str, chunk_count: int) -> dict[str, object]:
    timestamp = datetime(2026, 9, 24, 8, 30, tzinfo=timezone.utc)
    return {
        "id": uuid4(),
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


if __name__ == "__main__":
    unittest.main()
