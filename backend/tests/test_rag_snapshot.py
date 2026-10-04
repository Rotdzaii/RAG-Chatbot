from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rag_snapshot import (  # noqa: E402
    build_snapshot,
    payload_fingerprint,
    validate_snapshot,
    write_snapshot,
)


DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
CHUNK_ID = "22222222-2222-4222-8222-222222222222"


def document() -> dict[str, object]:
    return {
        "id": DOCUMENT_ID,
        "filename": "marketing.pdf",
        "mime_type": "application/pdf",
        "source_type": "file",
        "source_url": None,
        "category": None,
        "audience": None,
        "content_hash": None,
        "published_at": None,
        "last_checked_at": None,
        "effective_from": None,
        "effective_to": None,
        "created_at": "2026-10-01T08:00:00+00:00",
        "updated_at": "2026-10-01T08:00:00+00:00",
    }


def chunk() -> dict[str, object]:
    return {
        "id": CHUNK_ID,
        "document_id": DOCUMENT_ID,
        "chunk_index": 0,
        "content": "Nội dung Marketing đã trích xuất.",
        "embedding_present": True,
        "embedding_dimension": 768,
        "created_at": "2026-10-01T08:00:00+00:00",
    }


def snapshot(exported_at: str = "2026-10-01T09:00:00+00:00") -> dict[str, object]:
    return build_snapshot(
        documents=[document()],
        chunks=[chunk()],
        pipeline_config={
            "extraction": {},
            "chunking": {},
            "embedding": {
                "configured": {"model": "gemini-embedding-001"},
                "persisted_provenance": {
                    "model": "unknown",
                    "version": "unknown",
                },
            },
            "query_processing": {
                "history_used_for_rag": False,
                "query_rewriting": False,
                "rewritten_query": None,
            },
            "retrieval": {},
            "generation": {},
        },
        exported_at=exported_at,
    )


def refresh_fingerprint(value: dict[str, object]) -> None:
    value["fingerprint"] = payload_fingerprint(value["payload"])


class RagSnapshotTests(unittest.TestCase):
    def test_hash_is_stable_when_only_export_timestamp_changes(self) -> None:
        first = snapshot("2026-10-01T09:00:00+00:00")
        second = snapshot("2026-10-02T10:30:00+00:00")

        self.assertNotEqual(first["exported_at"], second["exported_at"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(validate_snapshot(first), [])
        self.assertEqual(validate_snapshot(second), [])

    def test_detects_modified_content_without_updated_hash(self) -> None:
        value = snapshot()
        payload = value["payload"]
        assert isinstance(payload, dict)
        chunks = payload["chunks"]
        assert isinstance(chunks, list)
        chunks[0]["content"] = "Nội dung đã bị thay đổi."

        errors = validate_snapshot(value)

        self.assertTrue(any("fingerprint mismatch" in error for error in errors))

    def test_detects_orphan_chunk(self) -> None:
        value = snapshot()
        payload = value["payload"]
        assert isinstance(payload, dict)
        chunks = payload["chunks"]
        assert isinstance(chunks, list)
        chunks[0]["document_id"] = "33333333-3333-4333-8333-333333333333"
        refresh_fingerprint(value)

        errors = validate_snapshot(value)

        self.assertTrue(any("orphan chunk" in error for error in errors))

    def test_detects_missing_and_wrong_embedding_dimensions(self) -> None:
        missing = snapshot()
        missing_payload = missing["payload"]
        assert isinstance(missing_payload, dict)
        missing_chunks = missing_payload["chunks"]
        assert isinstance(missing_chunks, list)
        missing_chunks[0]["embedding_present"] = False
        missing_chunks[0]["embedding_dimension"] = None
        refresh_fingerprint(missing)

        wrong = snapshot()
        wrong_payload = wrong["payload"]
        assert isinstance(wrong_payload, dict)
        wrong_chunks = wrong_payload["chunks"]
        assert isinstance(wrong_chunks, list)
        wrong_chunks[0]["embedding_dimension"] = 767
        refresh_fingerprint(wrong)

        missing_errors = validate_snapshot(missing)
        wrong_errors = validate_snapshot(wrong)

        self.assertTrue(any("embedding is missing" in error for error in missing_errors))
        self.assertTrue(
            any("embedding_dimension must be 768" in error for error in wrong_errors)
        )

    def test_detects_duplicate_ids_and_invalid_schema(self) -> None:
        value = snapshot()
        payload = value["payload"]
        assert isinstance(payload, dict)
        documents = payload["documents"]
        chunks = payload["chunks"]
        assert isinstance(documents, list)
        assert isinstance(chunks, list)
        documents.append(copy.deepcopy(documents[0]))
        chunks.append(copy.deepcopy(chunks[0]))
        refresh_fingerprint(value)

        errors = validate_snapshot(value)

        self.assertTrue(any("duplicate document id" in error for error in errors))
        self.assertTrue(any("duplicate chunk id" in error for error in errors))

        invalid = snapshot()
        invalid["schema_version"] = "99"
        self.assertTrue(
            any("schema_version" in error for error in validate_snapshot(invalid))
        )

    def test_does_not_overwrite_without_explicit_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            first = snapshot()
            second = snapshot("2026-10-03T11:00:00+00:00")
            write_snapshot(first, output)
            original = output.read_text(encoding="utf-8")

            with self.assertRaises(FileExistsError):
                write_snapshot(second, output)

            self.assertEqual(output.read_text(encoding="utf-8"), original)
            write_snapshot(second, output, overwrite=True)
            self.assertIn("2026-10-03T11:00:00+00:00", output.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
