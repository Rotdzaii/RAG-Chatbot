from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace

from sqlalchemy import CheckConstraint, Date, DateTime, String, UniqueConstraint


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.models import Document  # noqa: E402


class DocumentMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = Document.__table__

    def test_source_metadata_columns(self) -> None:
        source_type = self.table.c.source_type
        self.assertIsInstance(source_type.type, String)
        self.assertEqual(source_type.type.length, 4)
        self.assertFalse(source_type.nullable)
        self.assertEqual(source_type.default.arg, "file")
        self.assertEqual(str(source_type.server_default.arg), "'file'")

        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in self.table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertEqual(
            checks["ck_documents_source_type"], "source_type IN ('file', 'url')"
        )

        source_url = self.table.c.source_url
        self.assertTrue(source_url.nullable)
        unique_constraints = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in self.table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        self.assertEqual(
            unique_constraints["uq_documents_source_url"], ("source_url",)
        )

        for name in ("category", "audience"):
            column = self.table.c[name]
            self.assertIsInstance(column.type, String)
            self.assertTrue(column.nullable)

        content_hash = self.table.c.content_hash
        self.assertIsInstance(content_hash.type, String)
        self.assertEqual(content_hash.type.length, 64)
        self.assertTrue(content_hash.nullable)

    def test_source_timestamps_and_effective_dates(self) -> None:
        for name in ("published_at", "last_checked_at"):
            column = self.table.c[name]
            self.assertIsInstance(column.type, DateTime)
            self.assertTrue(column.type.timezone)
            self.assertTrue(column.nullable)

        for name in ("effective_from", "effective_to"):
            column = self.table.c[name]
            self.assertIsInstance(column.type, Date)
            self.assertTrue(column.nullable)

        updated_at = self.table.c.updated_at
        self.assertIsInstance(updated_at.type, DateTime)
        self.assertTrue(updated_at.type.timezone)
        self.assertFalse(updated_at.nullable)
        self.assertEqual(str(updated_at.server_default.arg), "now()")

    def test_existing_document_contract_is_preserved(self) -> None:
        self.assertFalse(self.table.c.filename.nullable)
        self.assertFalse(self.table.c.mime_type.nullable)
        self.assertEqual(Document.chunks.property.back_populates, "document")
        self.assertIn("delete-orphan", Document.chunks.property.cascade)


if __name__ == "__main__":
    unittest.main()
