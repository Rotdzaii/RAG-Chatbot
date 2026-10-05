from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.models import Chunk, Conversation, Document, Message  # noqa: E402


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


class ConversationHistoryModelTests(unittest.TestCase):
    def test_conversation_columns_relationship_and_index(self) -> None:
        table = Conversation.__table__

        self.assertFalse(table.c.user_id.nullable)
        self.assertIsInstance(table.c.title.type, Text)
        self.assertFalse(table.c.title.nullable)
        self.assertIsInstance(table.c.is_pinned.type, Boolean)
        self.assertFalse(table.c.is_pinned.nullable)
        self.assertEqual(str(table.c.is_pinned.server_default.arg), "false")
        for name in ("created_at", "updated_at"):
            self.assertIsInstance(table.c[name].type, DateTime)
            self.assertTrue(table.c[name].type.timezone)

        indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in table.indexes
        }
        self.assertEqual(
            indexes["ix_conversations_user_id_updated_at"],
            ("user_id", "updated_at"),
        )
        self.assertIn("delete-orphan", Conversation.messages.property.cascade)
        self.assertTrue(Conversation.messages.property.passive_deletes)

    def test_message_columns_role_constraint_and_cascade_foreign_key(self) -> None:
        table = Message.__table__

        self.assertIsInstance(table.c.content.type, Text)
        self.assertFalse(table.c.content.nullable)
        self.assertIsInstance(table.c.citations.type, JSONB)
        self.assertTrue(table.c.citations.nullable)
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertEqual(
            checks["ck_messages_role"], "role IN ('user', 'assistant')"
        )
        foreign_key = next(iter(table.c.conversation_id.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

        indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in table.indexes
        }
        self.assertEqual(
            indexes["ix_messages_conversation_id_created_at"],
            ("conversation_id", "created_at"),
        )

    def test_invalid_message_role_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Message role"):
            Message(role="system", content="invalid")


class ChunkProvenanceModelTests(unittest.TestCase):
    def test_page_range_columns_are_nullable_and_constrained(self) -> None:
        table = Chunk.__table__

        for name in ("page_start", "page_end"):
            self.assertTrue(table.c[name].nullable)

        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn("ck_chunks_page_range", checks)
        self.assertIn("page_start >= 1", checks["ck_chunks_page_range"])
        self.assertIn("page_end >= page_start", checks["ck_chunks_page_range"])


if __name__ == "__main__":
    unittest.main()
