from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rag_snapshot import build_snapshot  # noqa: E402
from validate_rag_eval_manifest import (  # noqa: E402
    manifest_summary,
    validate_manifest,
)


DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
FIRST_CHUNK_ID = "22222222-2222-4222-8222-222222222222"
SECOND_CHUNK_ID = "33333333-3333-4333-8333-333333333333"


def sample_snapshot() -> dict[str, object]:
    return build_snapshot(
        documents=[
            {
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
        ],
        chunks=[
            {
                "id": FIRST_CHUNK_ID,
                "document_id": DOCUMENT_ID,
                "chunk_index": 0,
                "content": "Thời gian đào tạo 3.5 năm.",
                "embedding_present": True,
                "embedding_dimension": 768,
                "created_at": "2026-10-01T08:00:00+00:00",
            },
            {
                "id": SECOND_CHUNK_ID,
                "document_id": DOCUMENT_ID,
                "chunk_index": 1,
                "content": "Một chunk khác không chứa evidence.",
                "embedding_present": True,
                "embedding_dimension": 768,
                "created_at": "2026-10-01T08:00:00+00:00",
            },
        ],
        pipeline_config={
            "extraction": {},
            "chunking": {},
            "embedding": {},
            "query_processing": {},
            "retrieval": {},
            "generation": {},
        },
        exported_at="2026-10-01T09:00:00+00:00",
    )


def sample_manifest(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "phase": "P0.2",
        "name": "Test manifest",
        "snapshot": {
            "path": "data/rag_snapshots/test.json",
            "fingerprint_algorithm": "sha256",
            "fingerprint": snapshot["fingerprint"],
        },
        "review_policy": {
            "score_only_review_status": "approved",
            "pending_answerability": "unknown",
            "history_is_fixture_not_gold": True,
            "required_facts_are_draft_until_approved": True,
        },
        "corpus_notes": [],
        "cases": [
            {
                "id": "TEST-001",
                "query_type": "standalone",
                "answerability": "unknown",
                "review_status": "pending_review",
                "reviewer": None,
                "reviewed_at": None,
                "question": "Ngành học trong bao lâu?",
                "history": [],
                "metadata": {
                    "history_fixture": False,
                    "history_is_gold": False,
                },
                "evidence": [
                    {
                        "kind": "supporting",
                        "document_id": DOCUMENT_ID,
                        "chunk_id": FIRST_CHUNK_ID,
                        "quote": "Thời gian đào tạo 3.5 năm.",
                    }
                ],
                "review_rationale": "Kiểm tra câu trả lời bám evidence thời gian.",
                "expected_behavior": "Trả lời theo evidence.",
                "required_behaviors": ["Trả lời trực tiếp câu hỏi"],
                "required_facts": ["3.5 năm"],
                "forbidden_claims": ["Một thời gian khác"],
                "fail_if": ["Không dùng evidence"],
                "metric_applicability": {
                    "retrieval": "pending_review",
                    "answer_quality": "pending_review",
                    "query_rewriting": "not_applicable",
                },
            }
        ],
    }


class RagEvalManifestTests(unittest.TestCase):
    def test_pending_manifest_with_zero_approved_is_valid(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)

        self.assertEqual(validate_manifest(manifest, snapshot), [])
        self.assertEqual(
            manifest_summary(manifest),
            {
                "total": 1,
                "approved": 0,
                "pending_review": 1,
                "rejected": 0,
                "scored": 0,
                "excluded": 1,
            },
        )

    def test_rejects_wrong_snapshot_fingerprint(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        manifest_snapshot = manifest["snapshot"]
        assert isinstance(manifest_snapshot, dict)
        manifest_snapshot["fingerprint"] = "0" * 64

        errors = validate_manifest(manifest, snapshot)

        self.assertTrue(any("snapshot fingerprint mismatch" in error for error in errors))

    def test_rejects_quote_attached_to_wrong_chunk(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        cases = manifest["cases"]
        assert isinstance(cases, list)
        evidence = cases[0]["evidence"]
        assert isinstance(evidence, list)
        evidence[0]["chunk_id"] = SECOND_CHUNK_ID

        errors = validate_manifest(manifest, snapshot)

        self.assertTrue(
            any("quote is not present in the referenced chunk" in error for error in errors)
        )

    def test_approved_case_requires_review_information(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        cases = manifest["cases"]
        assert isinstance(cases, list)
        case = cases[0]
        case["review_status"] = "approved"
        case["answerability"] = "answerable"
        case["metric_applicability"]["retrieval"] = "applicable"

        errors = validate_manifest(manifest, snapshot)

        self.assertTrue(any("reviewer must be a non-empty string" in error for error in errors))
        self.assertTrue(
            any("reviewed_at must be a non-empty string" in error for error in errors)
        )

    def test_history_fixture_metadata_is_validated(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        cases = manifest["cases"]
        assert isinstance(cases, list)
        case = cases[0]
        metadata = case["metadata"]
        assert isinstance(metadata, dict)
        metadata["history_fixture"] = True
        metadata["history_is_gold"] = True

        errors = validate_manifest(manifest, snapshot)

        self.assertTrue(
            any("history_is_gold must be false" in error for error in errors)
        )
        self.assertTrue(
            any("history must be non-empty for a history fixture" in error for error in errors)
        )

    def test_review_rationale_can_exist_without_extended_rubric(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        cases = manifest["cases"]
        assert isinstance(cases, list)
        case = cases[0]
        del case["metadata"]
        del case["required_behaviors"]

        self.assertEqual(validate_manifest(manifest, snapshot), [])


if __name__ == "__main__":
    unittest.main()
