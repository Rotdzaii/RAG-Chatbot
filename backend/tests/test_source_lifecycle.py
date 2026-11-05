import sys
import unittest
from hashlib import sha256
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.chunking import TextChunk  # noqa: E402
from rag.extraction import ExtractedContent  # noqa: E402
from rag.index_provenance import CHUNKING_PROFILE, current_embedding_profile  # noqa: E402
from rag.models import Document, SourceFileVersion  # noqa: E402
from rag.source_files import store_version, read_version  # noqa: E402
from rag.source_lifecycle import (  # noqa: E402
    SourceChanged, SourceNotFound, SourceTypeMismatch, delete_source, replace_source,
)


def existing_source(*, source_type="file", content=b"old"):
    return Document(
        id=uuid4(), filename="old.txt", mime_type="text/plain",
        source_type=source_type,
        source_url="https://www.vlu.edu.vn/old" if source_type == "url" else None,
        content_hash=sha256(content).hexdigest(),
        embedding_profile=current_embedding_profile(),
        chunking_profile=CHUNKING_PROFILE,
    )


class SourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        storage_patch = patch("rag.source_files.source_file_directory", return_value=Path(self.storage.name))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)

    def test_unchanged_url_skips_embedding_and_updates_check_time(self):
        doc = existing_source(source_type="url")
        session = Mock()
        session.scalar.side_effect = [doc, 2]
        with patch("rag.ingestion.embed_documents") as embed:
            result = replace_source(
                session, doc.id, source_type="url", filename="old.txt",
                mime_type="text/plain", content=b"old", source_url=doc.source_url,
            )
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(result.chunk_count, 2)
        self.assertIsNotNone(doc.last_checked_at)
        embed.assert_not_called()
        session.execute.assert_not_called()
        session.commit.assert_called_once_with()

    def test_unchanged_legacy_file_gains_original_without_reembedding(self):
        doc = existing_source()
        session = Mock()
        session.scalar.side_effect = [doc, 1, uuid4()]
        with patch("rag.ingestion.embed_documents") as embed:
            result = replace_source(
                session, doc.id, source_type="file", filename="old.txt",
                mime_type="text/plain", content=b"old",
            )
        self.assertEqual(result.status, "updated")
        embed.assert_not_called()
        version = session.add.call_args.args[0]
        self.assertEqual(read_version(version.id, version.mime_type, version.content_hash, version.byte_size), b"old")
        self.assertIn("source_file_version_id", str(session.execute.call_args.args[0]))
        session.commit.assert_called_once()

    def test_changed_file_replaces_chunks_after_embedding_in_one_commit(self):
        doc = existing_source()
        session = Mock()
        session.scalar.side_effect = [doc, doc]
        events = []
        session.execute.side_effect = lambda _stmt: events.append("delete-old")
        session.add_all.side_effect = lambda _chunks: events.append("add-new")
        session.commit.side_effect = lambda: events.append("commit")
        with (
            patch("rag.ingestion.extract_content", return_value=ExtractedContent("new text")),
            patch("rag.ingestion.chunk_text_with_offsets", return_value=[TextChunk("new text", 0, 8)]),
            patch("rag.ingestion.embed_documents", side_effect=lambda _texts: events.append("embed") or [[0.1, 0.2]]),
        ):
            result = replace_source(
                session, doc.id, source_type="file", filename="new.txt",
                mime_type="text/plain", content=b"new bytes",
            )
        self.assertEqual(events, ["embed", "delete-old", "add-new", "commit"])
        self.assertEqual(result.status, "updated")
        self.assertEqual(result.document_id, doc.id)
        self.assertEqual(doc.content_hash, sha256(b"new bytes").hexdigest())
        self.assertEqual(session.add_all.call_args.args[0][0].document_id, doc.id)
        new_version = session.add.call_args.args[0]
        self.assertEqual(session.add_all.call_args.args[0][0].source_file_version_id, new_version.id)
        self.assertEqual(read_version(new_version.id, "text/plain", new_version.content_hash, new_version.byte_size), b"new bytes")
        session.rollback.assert_called_once_with()  # Releases the pre-embedding lock.

    def test_embedding_failure_never_deletes_old_chunks(self):
        doc = existing_source()
        session = Mock()
        session.scalar.return_value = doc
        with (
            patch("rag.ingestion.extract_content", return_value=ExtractedContent("new text")),
            patch("rag.ingestion.chunk_text_with_offsets", return_value=[TextChunk("new text", 0, 8)]),
            patch("rag.ingestion.embed_documents", side_effect=RuntimeError("provider failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                replace_source(session, doc.id, source_type="file", filename="new.txt",
                               mime_type="text/plain", content=b"new bytes")
        session.execute.assert_not_called()
        session.add_all.assert_not_called()
        session.commit.assert_not_called()
        self.assertEqual(doc.content_hash, sha256(b"old").hexdigest())

    def test_concurrent_update_rejected_without_deleting_newer_chunks(self):
        old = existing_source()
        newer = existing_source(content=b"changed elsewhere")
        newer.id = old.id
        session = Mock()
        session.scalar.side_effect = [old, newer]
        with (
            patch("rag.ingestion.extract_content", return_value=ExtractedContent("new text")),
            patch("rag.ingestion.chunk_text_with_offsets", return_value=[TextChunk("new text", 0, 8)]),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]),
        ):
            with self.assertRaises(SourceChanged):
                replace_source(session, old.id, source_type="file", filename="new.txt",
                               mime_type="text/plain", content=b"new bytes")
        session.execute.assert_not_called()
        session.commit.assert_not_called()

    def test_index_profile_change_rebuilds_even_with_same_bytes(self):
        doc = existing_source()
        doc.chunking_profile = "old-profile"
        session = Mock()
        session.scalar.side_effect = [doc, doc]
        with (
            patch("rag.ingestion.extract_content", return_value=ExtractedContent("new text")),
            patch("rag.ingestion.chunk_text_with_offsets", return_value=[TextChunk("new text", 0, 8)]),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]) as embed,
        ):
            result = replace_source(session, doc.id, source_type="file", filename="old.txt",
                                    mime_type="text/plain", content=b"old")
        self.assertEqual(result.status, "updated")
        self.assertEqual(doc.chunking_profile, CHUNKING_PROFILE)
        embed.assert_called_once_with(["new text"])
        session.execute.assert_called_once()

    def test_commit_failure_rolls_back_replaced_chunks(self):
        doc = existing_source()
        session = Mock()
        session.scalar.side_effect = [doc, doc]
        session.commit.side_effect = OSError("database failed")
        with (
            patch("rag.ingestion.extract_content", return_value=ExtractedContent("new text")),
            patch("rag.ingestion.chunk_text_with_offsets", return_value=[TextChunk("new text", 0, 8)]),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]),
        ):
            with self.assertRaises(OSError):
                replace_source(session, doc.id, source_type="file", filename="new.txt",
                               mime_type="text/plain", content=b"new")
        session.execute.assert_called_once()
        session.rollback.assert_called()  # The second rollback undoes DELETE and INSERT.
        self.assertEqual(list(Path(self.storage.name).iterdir()), [])

    def test_replacement_preserves_old_file_until_source_is_deleted(self):
        doc = existing_source()
        old = SourceFileVersion(
            id=uuid4(), document_id=doc.id, mime_type="text/plain",
            content_hash=sha256(b"old").hexdigest(), byte_size=3,
        )
        doc.file_versions.append(old)
        store_version(old.id, old.mime_type, b"old")
        session = Mock()
        session.scalar.side_effect = [doc, doc]
        with (
            patch("rag.ingestion.extract_content", return_value=ExtractedContent("new text")),
            patch("rag.ingestion.chunk_text_with_offsets", return_value=[TextChunk("new text", 0, 8)]),
            patch("rag.ingestion.embed_documents", return_value=[[0.1, 0.2]]),
        ):
            replace_source(session, doc.id, source_type="file", filename="new.txt",
                           mime_type="text/plain", content=b"new")
        new = session.add.call_args.args[0]
        self.assertNotEqual(old.id, new.id)
        self.assertEqual(read_version(old.id, old.mime_type, old.content_hash, old.byte_size), b"old")
        self.assertEqual(read_version(new.id, new.mime_type, new.content_hash, new.byte_size), b"new")
        # A later delete revokes both versions, including historical citations.
        doc.file_versions.append(new)
        deletion = Mock()
        deletion.scalar.return_value = doc
        self.assertTrue(delete_source(deletion, doc.id))
        self.assertEqual(list(Path(self.storage.name).iterdir()), [])

    def test_wrong_type_or_missing_source_skips_embedding(self):
        doc = existing_source(source_type="url")
        session = Mock()
        with patch("rag.ingestion.embed_documents") as embed:
            session.scalar.return_value = None
            with self.assertRaises(SourceNotFound):
                replace_source(session, doc.id, source_type="file", filename="x.txt",
                               mime_type="text/plain", content=b"x")
            session.scalar.return_value = doc
            with self.assertRaises(SourceTypeMismatch):
                replace_source(session, doc.id, source_type="file", filename="x.txt",
                               mime_type="text/plain", content=b"x")
        embed.assert_not_called()
        session.execute.assert_not_called()

    def test_delete_commits_document_and_rolls_back_on_failure(self):
        doc = existing_source()
        session = Mock()
        session.scalar.return_value = doc
        self.assertTrue(delete_source(session, doc.id))
        session.delete.assert_called_once_with(doc)
        session.commit.assert_called_once_with()

        failure = Mock()
        failure.scalar.return_value = doc
        failure.commit.side_effect = RuntimeError("commit failed")
        with self.assertRaises(RuntimeError):
            delete_source(failure, doc.id)
        failure.rollback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
