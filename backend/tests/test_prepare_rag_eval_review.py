from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from prepare_rag_eval_review import main, prepare_review_manifest  # noqa: E402
from rag_snapshot import payload_fingerprint  # noqa: E402
from test_rag_eval_manifest import sample_manifest, sample_snapshot  # noqa: E402
from validate_rag_eval_manifest import validate_manifest  # noqa: E402


def revised_snapshot(old):
    revised = copy.deepcopy(old)
    revised["payload"]["pipeline_config"]["generation"]["revision"] = "v2"
    revised["fingerprint"] = payload_fingerprint(revised["payload"])
    return revised


class PrepareReviewTests(unittest.TestCase):
    def test_reanchors_exact_evidence_but_resets_prior_approval(self):
        old = sample_snapshot()
        source = sample_manifest(old)
        case = source["cases"][0]
        case.update({
            "answerability": "answerable", "review_status": "approved",
            "reviewer": "old-reviewer", "reviewed_at": "2026-10-04T10:00:00+07:00",
        })
        case["metric_applicability"].update({
            "retrieval": "applicable", "answer_quality": "applicable"
        })
        revised = revised_snapshot(old)

        draft = prepare_review_manifest(source, revised, snapshot_ref="data/rag_snapshots/p6.json")

        self.assertEqual(validate_manifest(draft, revised), [])
        self.assertEqual(draft["snapshot"]["fingerprint"], revised["fingerprint"])
        self.assertEqual(draft["cases"][0]["review_status"], "pending_review")
        self.assertEqual(draft["cases"][0]["answerability"], "unknown")
        self.assertIsNone(draft["cases"][0]["reviewer"])
        self.assertEqual(draft["cases"][0]["evidence"], case["evidence"])
        self.assertEqual(source["cases"][0]["review_status"], "approved")

    def test_rejects_changed_or_missing_evidence_in_new_snapshot(self):
        old = sample_snapshot()
        source = sample_manifest(old)
        revised = copy.deepcopy(old)
        revised["payload"]["chunks"][0]["content"] = "Unrelated replacement"
        revised["fingerprint"] = payload_fingerprint(revised["payload"])
        with self.assertRaisesRegex(ValueError, "Evidence or manifest is invalid"):
            prepare_review_manifest(source, revised, snapshot_ref="data/rag_snapshots/p6.json")

    def test_rejects_invalid_snapshot_before_writing(self):
        old = sample_snapshot()
        revised = revised_snapshot(old)
        revised["fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Snapshot is invalid"):
            prepare_review_manifest(sample_manifest(old), revised, snapshot_ref="snapshot.json")

    def test_cli_refuses_existing_output_without_overwriting(self):
        old = sample_snapshot()
        revised = revised_snapshot(old)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path, snapshot_path, output = (
                root / "source.json", root / "snapshot.json", root / "draft.json"
            )
            source_path.write_text(json.dumps(sample_manifest(old)), encoding="utf-8")
            snapshot_path.write_text(json.dumps(revised), encoding="utf-8")
            args = [str(source_path), "--snapshot", str(snapshot_path),
                    "--snapshot-ref", "data/rag_snapshots/p6.json", "--output", str(output)]
            self.assertEqual(main(args), 0)
            before = output.read_bytes()
            self.assertEqual(main(args), 1)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
