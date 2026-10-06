from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rag_p6_lifecycle import (  # noqa: E402
    IndexedChunk, IndexedSource, SyntheticEmbeddingFailure, run_lifecycle_gate,
)
from rag_p6_preflight import build_preflight_report  # noqa: E402
from run_rag_p6_lifecycle import main as lifecycle_main  # noqa: E402
from run_rag_p6_preflight import main as preflight_main  # noqa: E402
from test_rag_eval_manifest import sample_manifest, sample_snapshot  # noqa: E402


PROFILE = "gemini-embedding-001:768:l2:v1"
CHUNKING = "fixed-character-window:1000:150:v1"


def approved_manifest(snapshot):
    manifest = sample_manifest(snapshot)
    case = manifest["cases"][0]
    case["review_status"] = "approved"
    case["answerability"] = "answerable"
    case["reviewer"] = "reviewer"
    case["reviewed_at"] = "2026-10-06T09:00:00+07:00"
    case["metric_applicability"]["retrieval"] = "applicable"
    case["metric_applicability"]["answer_quality"] = "applicable"
    return manifest


class FakeAdapter:
    def __init__(self):
        self.source = None
        self.calls = []
        self.fail_at = None

    def create(self, filename, content):
        self.calls.append("create")
        source_id = uuid4()
        self._set(source_id, content)
        return source_id

    def _set(self, source_id, content):
        self.source = IndexedSource(
            source_id, sha256(content).hexdigest(), PROFILE, CHUNKING,
            (IndexedChunk(uuid4(), content.decode(), 768),),
        )

    def replace(self, source_id, filename, content, *, fail_embedding=False):
        operation = "inject_failure" if fail_embedding else "replace"
        self.calls.append(operation)
        if operation == self.fail_at:
            raise RuntimeError("simulated provider failure with sensitive details")
        if fail_embedding:
            raise SyntheticEmbeddingFailure()
        if self.source.content_hash == sha256(content).hexdigest():
            return SimpleNamespace(status="unchanged", document_id=source_id)
        self._set(source_id, content)
        return SimpleNamespace(status="updated", document_id=source_id)

    def inspect(self, source_id):
        return self.source

    def delete(self, source_id):
        self.calls.append("delete")
        self.source = None
        return True


class P6AcceptanceTests(unittest.TestCase):
    def test_preflight_ready_requires_valid_approved_manifest(self):
        snapshot = sample_snapshot()
        report = build_preflight_report(snapshot, [("approved.json", approved_manifest(snapshot))])
        self.assertEqual(report["status"], "ready_for_live_compatibility_check")
        self.assertFalse(report["live_corpus_verified"])
        self.assertIsNone(report["quality_score"])

    def test_preflight_blocks_pending_and_stale_manifest(self):
        snapshot = sample_snapshot()
        pending = sample_manifest(snapshot)
        stale = copy.deepcopy(approved_manifest(snapshot))
        stale["snapshot"]["fingerprint"] = "0" * 64
        report = build_preflight_report(snapshot, [("pending", pending), ("stale", stale)])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["manifests"][0]["status"], "pending_review")
        self.assertEqual(report["manifests"][1]["status"], "invalid")
        self.assertTrue(any("fingerprint mismatch" in message
                            for message in report["manifests"][1]["errors"]))

    def test_invalid_snapshot_blocks_without_iterating_malformed_payload(self):
        snapshot = sample_snapshot()
        snapshot["payload"]["documents"] = 17
        report = build_preflight_report(snapshot, [("draft", sample_manifest(sample_snapshot()))])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["snapshot"]["status"], "invalid")
        self.assertEqual(report["manifests"][0]["status"], "invalid")

    def test_preflight_cli_reports_and_does_not_overwrite(self):
        snapshot = sample_snapshot()
        manifest = approved_manifest(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, manifest_path, output = (
                root / "snapshot.json", root / "manifest.json", root / "result.json"
            )
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            args = ["--snapshot", str(snapshot_path), "--manifest", str(manifest_path),
                    "--output", str(output)]
            self.assertEqual(preflight_main(args), 0)
            original = output.read_bytes()
            self.assertEqual(preflight_main(args), 1)
            self.assertEqual(output.read_bytes(), original)

    def test_lifecycle_gate_preserves_ids_on_skip_and_cleans_up(self):
        adapter = FakeAdapter()
        report = run_lifecycle_gate(adapter, embedding_profile=PROFILE,
                                    chunking_profile=CHUNKING)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["steps"]), 5)
        self.assertEqual(adapter.calls, ["create", "replace", "replace", "inject_failure", "delete"])
        self.assertIsNone(adapter.source)

    def test_lifecycle_failure_cleans_up_and_sanitizes_error(self):
        adapter = FakeAdapter()
        adapter.fail_at = "replace"
        report = run_lifecycle_gate(adapter, embedding_profile=PROFILE,
                                    chunking_profile=CHUNKING)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_stage"], "unchanged")
        self.assertEqual(report["error_type"], "RuntimeError")
        self.assertEqual(report["cleanup_status"], "completed")
        self.assertIsNone(adapter.source)
        self.assertNotIn("sensitive details", json.dumps(report))

    def test_cleanup_failure_keeps_document_id_for_manual_recovery(self):
        adapter = FakeAdapter()
        adapter.fail_at = "replace"
        adapter.delete = Mock(side_effect=RuntimeError("secret database URL"))
        report = run_lifecycle_gate(adapter, embedding_profile=PROFILE,
                                    chunking_profile=CHUNKING)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["cleanup_status"], "failed")
        self.assertIsNotNone(report["document_id"])
        self.assertNotIn("secret database URL", json.dumps(report))

    def test_dry_run_imports_no_database_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dry.json"
            with patch("run_rag_p6_lifecycle._live_adapter") as live:
                self.assertEqual(lifecycle_main(["--output", str(output)]), 0)
                self.assertEqual(lifecycle_main(["--output", str(output)]), 1)
                live.assert_not_called()
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "not_run")
        self.assertFalse(report["database_access"])
        self.assertFalse(report["provider_access"])


if __name__ == "__main__":
    unittest.main()
