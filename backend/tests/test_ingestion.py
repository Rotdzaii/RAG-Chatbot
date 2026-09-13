import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.ingestion import ingest_document


class IngestDocumentTests(unittest.TestCase):
    def test_persists_document_with_ordered_chunks(self) -> None:
        session = Mock()

        with (
            patch("rag.ingestion.extract_text", return_value="extracted text"),
            patch("rag.ingestion.chunk_text", return_value=["first", "second"]),
            patch(
                "rag.ingestion.embed_documents",
                return_value=[[0.1, 0.2], [0.3, 0.4]],
            ),
        ):
            document = ingest_document(
                session, "notes.txt", "text/plain", b"source content"
            )

        self.assertEqual(document.filename, "notes.txt")
        self.assertEqual(document.mime_type, "text/plain")
        self.assertEqual([chunk.chunk_index for chunk in document.chunks], [0, 1])
        self.assertEqual([chunk.content for chunk in document.chunks], ["first", "second"])
        self.assertEqual(
            [chunk.embedding for chunk in document.chunks], [[0.1, 0.2], [0.3, 0.4]]
        )
        session.add.assert_called_once_with(document)
        session.commit.assert_called_once_with()
        session.rollback.assert_not_called()

    def test_preprocessing_failure_does_not_mutate_session(self) -> None:
        session = Mock()

        with patch("rag.ingestion.extract_text", side_effect=ValueError("invalid")):
            with self.assertRaisesRegex(ValueError, "invalid"):
                ingest_document(session, "notes.txt", "text/plain", b"source")

        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_rejects_embedding_count_mismatch_without_mutating_session(self) -> None:
        session = Mock()

        with (
            patch("rag.ingestion.extract_text", return_value="extracted text"),
            patch("rag.ingestion.chunk_text", return_value=["first", "second"]),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]),
        ):
            with self.assertRaisesRegex(ValueError, "counts must match"):
                ingest_document(session, "notes.txt", "text/plain", b"source")

        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_rolls_back_when_commit_fails(self) -> None:
        session = Mock()
        session.commit.side_effect = RuntimeError("database error")

        with (
            patch("rag.ingestion.extract_text", return_value="extracted text"),
            patch("rag.ingestion.chunk_text", return_value=["chunk"]),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]),
        ):
            with self.assertRaisesRegex(RuntimeError, "database error"):
                ingest_document(session, "notes.txt", "text/plain", b"source")

        session.add.assert_called_once()
        session.commit.assert_called_once_with()
        session.rollback.assert_called_once_with()

    def test_rejects_blank_filename_without_mutating_session(self) -> None:
        session = Mock()

        with self.assertRaisesRegex(ValueError, "Filename must not be blank"):
            ingest_document(session, " \t", "text/plain", b"source")

        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
