from hashlib import sha256
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.chunking import TextChunk
from rag.extraction import ExtractedContent
from rag.ingestion import ingest_document
from rag.index_provenance import CHUNKING_PROFILE, current_embedding_profile


class IngestDocumentTests(unittest.TestCase):
    def test_persists_document_with_ordered_chunks(self) -> None:
        session = Mock()

        with (
            patch(
                "rag.ingestion.extract_content",
                return_value=ExtractedContent("first second"),
            ),
            patch(
                "rag.ingestion.chunk_text_with_offsets",
                return_value=[
                    TextChunk("first", 0, 5),
                    TextChunk("second", 6, 12),
                ],
            ),
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
        self.assertEqual(
            document.content_hash, sha256(b"source content").hexdigest()
        )
        self.assertEqual(document.embedding_profile, current_embedding_profile())
        self.assertEqual(document.chunking_profile, CHUNKING_PROFILE)
        self.assertEqual([chunk.chunk_index for chunk in document.chunks], [0, 1])
        self.assertEqual([chunk.content for chunk in document.chunks], ["first", "second"])
        self.assertEqual(
            [(chunk.page_start, chunk.page_end) for chunk in document.chunks],
            [(None, None), (None, None)],
        )
        self.assertEqual(
            [chunk.embedding for chunk in document.chunks], [[0.1, 0.2], [0.3, 0.4]]
        )
        session.add.assert_called_once_with(document)
        session.commit.assert_called_once_with()
        session.rollback.assert_not_called()

    def test_preprocessing_failure_does_not_mutate_session(self) -> None:
        session = Mock()

        with patch(
            "rag.ingestion.extract_content", side_effect=ValueError("invalid")
        ):
            with self.assertRaisesRegex(ValueError, "invalid"):
                ingest_document(session, "notes.txt", "text/plain", b"source")

        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_rejects_embedding_count_mismatch_without_mutating_session(self) -> None:
        session = Mock()

        with (
            patch(
                "rag.ingestion.extract_content",
                return_value=ExtractedContent("first second"),
            ),
            patch(
                "rag.ingestion.chunk_text_with_offsets",
                return_value=[
                    TextChunk("first", 0, 5),
                    TextChunk("second", 6, 12),
                ],
            ),
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
            patch(
                "rag.ingestion.extract_content",
                return_value=ExtractedContent("chunk"),
            ),
            patch(
                "rag.ingestion.chunk_text_with_offsets",
                return_value=[TextChunk("chunk", 0, 5)],
            ),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]),
        ):
            with self.assertRaisesRegex(RuntimeError, "database error"):
                ingest_document(session, "notes.txt", "text/plain", b"source")

        session.add.assert_called_once()
        session.commit.assert_called_once_with()
        session.rollback.assert_called_once_with()

    def test_pdf_chunks_keep_page_ranges_across_a_page_boundary(self) -> None:
        session = Mock()
        first_page = "A" * 600
        second_page = "B" * 600
        loader_pages = [
            SimpleNamespace(page_content=first_page),
            SimpleNamespace(page_content=second_page),
        ]

        with (
            patch("rag.extraction.PyPDFLoader.load", return_value=loader_pages),
            patch(
                "rag.ingestion.embed_documents",
                return_value=[[0.1], [0.2]],
            ) as embed,
        ):
            document = ingest_document(
                session, "handbook.pdf", "application/pdf", b"pdf bytes"
            )

        embed.assert_called_once_with(
            [first_page + "\n\n" + second_page[:398], second_page[248:]]
        )
        self.assertEqual(
            [(chunk.page_start, chunk.page_end) for chunk in document.chunks],
            [(1, 2), (2, 2)],
        )
        self.assertEqual(document.content_hash, sha256(b"pdf bytes").hexdigest())
        session.add.assert_called_once_with(document)
        session.commit.assert_called_once_with()

    def test_pdf_extraction_error_never_embeds_or_mutates_session(self) -> None:
        session = Mock()

        with (
            patch(
                "rag.extraction.PyPDFLoader.load",
                side_effect=ValueError("loader failed"),
            ),
            patch("rag.ingestion.embed_documents") as embed,
        ):
            with self.assertRaisesRegex(ValueError, "loader failed"):
                ingest_document(
                    session, "broken.pdf", "application/pdf", b"broken"
                )

        embed.assert_not_called()
        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_txt_chunks_have_no_page_range(self) -> None:
        session = Mock()

        with patch(
            "rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]
        ):
            document = ingest_document(
                session,
                "notes.txt",
                "text/plain",
                b"plain text without pages",
            )

        self.assertEqual(len(document.chunks), 1)
        self.assertIsNone(document.chunks[0].page_start)
        self.assertIsNone(document.chunks[0].page_end)
        self.assertEqual(
            document.content_hash,
            sha256(b"plain text without pages").hexdigest(),
        )

    def test_rejects_blank_filename_without_mutating_session(self) -> None:
        session = Mock()

        with self.assertRaisesRegex(ValueError, "Filename must not be blank"):
            ingest_document(session, " \t", "text/plain", b"source")

        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
