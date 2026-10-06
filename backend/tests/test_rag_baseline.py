from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_rag_baseline as baseline_cli  # noqa: E402
from rag_baseline import (  # noqa: E402
    aggregate_retrieval_metrics,
    build_dry_run_report,
    case_retrieval_metrics,
    ensure_live_snapshot_matches,
    run_live_baseline,
    select_cases,
    validate_citation_indices,
    write_run_output,
)
from test_rag_eval_manifest import sample_manifest, sample_snapshot  # noqa: E402


def approved_manifest() -> tuple[dict[str, object], dict[str, object]]:
    snapshot = sample_snapshot()
    manifest = sample_manifest(snapshot)
    cases = manifest["cases"]
    assert isinstance(cases, list)
    case = cases[0]
    case["review_status"] = "approved"
    case["answerability"] = "answerable"
    case["reviewer"] = "reviewer@example.edu"
    case["reviewed_at"] = "2026-10-02T09:00:00+07:00"
    case["metric_applicability"]["retrieval"] = "applicable"
    return manifest, snapshot


class RagBaselineTests(unittest.TestCase):
    def test_filters_only_approved_cases_and_reports_exclusions(self) -> None:
        manifest, _ = approved_manifest()
        cases = manifest["cases"]
        assert isinstance(cases, list)
        pending = dict(cases[0])
        pending["id"] = "TEST-002"
        pending["review_status"] = "pending_review"
        cases.append(pending)

        selected, excluded = select_cases(manifest)

        self.assertEqual([case["id"] for case in selected], ["TEST-001"])
        self.assertEqual(
            excluded,
            [
                {
                    "case_id": "TEST-002",
                    "review_status": "pending_review",
                    "reason": "review_status_pending_review",
                }
            ],
        )

    def test_metrics_deduplicate_chunk_ids_and_use_expected_denominators(self) -> None:
        manifest, _ = approved_manifest()
        case = manifest["cases"][0]
        first = case["evidence"][0]
        duplicate = dict(first)
        second = dict(first)
        second["chunk_id"] = "44444444-4444-4444-8444-444444444444"
        case["evidence"] = [first, duplicate, second]

        metrics = case_retrieval_metrics(
            case,
            [
                "99999999-9999-4999-8999-999999999999",
                second["chunk_id"],
                first["chunk_id"],
                first["chunk_id"],
            ],
        )

        self.assertEqual(
            metrics["expected_chunk_ids"],
            [first["chunk_id"], second["chunk_id"]],
        )
        self.assertEqual(len(metrics["retrieved_chunk_ids"]), 3)
        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["reciprocal_rank"], 0.5)
        self.assertTrue(metrics["evidence_hit"])
        self.assertTrue(metrics["all_evidence_hit"])

        missed = dict(metrics)
        missed.update(
            {
                "recall_at_k": 0.0,
                "reciprocal_rank": 0.0,
                "evidence_hit": False,
                "all_evidence_hit": False,
            }
        )
        excluded = {
            "status": "not_applicable",
            "included_in_aggregate": False,
        }
        aggregate = aggregate_retrieval_metrics(
            [
                {"retrieval_metrics": metrics},
                {"retrieval_metrics": missed},
                {"retrieval_metrics": excluded},
            ]
        )
        self.assertEqual(aggregate["applicable_cases"], 2)
        self.assertEqual(aggregate["excluded_cases"], 1)
        self.assertEqual(aggregate["recall_at_k_macro"], 0.5)
        self.assertEqual(aggregate["mrr_at_k"], 0.25)
        self.assertEqual(aggregate["evidence_hit_at_k"], 0.5)
        self.assertEqual(aggregate["all_evidence_hit_at_k"], 0.5)

    def test_not_applicable_case_is_excluded_from_metrics(self) -> None:
        manifest, _ = approved_manifest()
        case = manifest["cases"][0]
        case["metric_applicability"]["retrieval"] = "not_applicable"

        metrics = case_retrieval_metrics(case, [case["evidence"][0]["chunk_id"]])
        aggregate = aggregate_retrieval_metrics([{"retrieval_metrics": metrics}])

        self.assertFalse(metrics["included_in_aggregate"])
        self.assertEqual(aggregate["applicable_cases"], 0)
        self.assertIsNone(aggregate["recall_at_k_macro"])

    def test_citation_indices_are_checked_against_returned_sources(self) -> None:
        result = validate_citation_indices("Đúng [1], sai [3], lặp [1].", 2)

        self.assertFalse(result["valid"])
        self.assertEqual(result["cited_indices"], [1, 3])
        self.assertEqual(result["invalid_indices"], [3])

    def test_grouped_citations_match_frontend_syntax(self) -> None:
        result = validate_citation_indices("Nguồn [2, 1; 2], [3](https://example.test)", 2)

        self.assertTrue(result["valid"])
        self.assertEqual(result["cited_indices"], [2, 1])

    def test_case_error_is_recorded_without_leaking_exception_message(self) -> None:
        manifest, snapshot = approved_manifest()
        times = iter((1.0, 1.125))

        report = run_live_baseline(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            ask=lambda _question: (_ for _ in ()).throw(
                RuntimeError("postgresql://user:secret@host/database")
            ),
            clock=lambda: next(times),
        )

        case = report["cases"][0]
        self.assertEqual(case["status"], "error")
        self.assertEqual(case["error"]["type"], "RuntimeError")
        self.assertEqual(case["error"]["message"], "Case execution failed")
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual(case["latency_ms"], 125.0)

    def test_live_result_uses_qa_sources_without_second_retrieval(self) -> None:
        manifest, snapshot = approved_manifest()
        evidence_id = manifest["cases"][0]["evidence"][0]["chunk_id"]
        ask = Mock(
            return_value=SimpleNamespace(
                answer="Thời gian là 3.5 năm [1].",
                sources=[
                    SimpleNamespace(
                        chunk_id=evidence_id,
                        document_id="11111111-1111-4111-8111-111111111111",
                        filename="marketing.pdf",
                        chunk_index=0,
                        content="Thời gian đào tạo 3.5 năm.",
                        cosine_distance=0.1,
                    )
                ],
            )
        )

        report = run_live_baseline(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            ask=ask,
        )

        ask.assert_called_once_with("Ngành học trong bao lâu?")
        case = report["cases"][0]
        self.assertFalse(case["history_used"])
        self.assertIsNone(case["rewritten_query"])
        self.assertEqual(case["retrieved_chunks"][0]["chunk_id"], evidence_id)
        self.assertTrue(case["citation_index_validation"]["valid"])
        self.assertEqual(report["retrieval_metrics"]["recall_at_k_macro"], 1.0)
        self.assertFalse(report["execution_policy"]["second_retrieval_for_observation"])

    def test_dry_run_does_not_select_pending_cases_or_need_live_dependencies(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        report = build_dry_run_report(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
        )

        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["selection"]["selected_cases"], 0)
        self.assertEqual(report["selection"]["excluded_cases"], 1)
        self.assertEqual(report["cases"], [])
        self.assertFalse(report["execution_policy"]["history_used"])
        self.assertIsNone(report["execution_policy"]["rewritten_query"])

    def test_live_cli_with_zero_approved_stops_before_loading_services(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            snapshot_path = root / "snapshot.json"
            output_path = root / "run.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            with patch.object(baseline_cli, "_load_live_dependencies") as loader:
                result = baseline_cli.main(
                    [
                        str(manifest_path),
                        "--snapshot",
                        str(snapshot_path),
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(result, 2)
            loader.assert_not_called()
            self.assertFalse(output_path.exists())

    def test_dry_run_cli_writes_report_without_loading_services_or_overwrite(self) -> None:
        snapshot = sample_snapshot()
        manifest = sample_manifest(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            snapshot_path = root / "snapshot.json"
            output_path = root / "run.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            with patch.object(baseline_cli, "_load_live_dependencies") as loader:
                result = baseline_cli.main(
                    [
                        str(manifest_path),
                        "--snapshot",
                        str(snapshot_path),
                        "--output",
                        str(output_path),
                        "--dry-run",
                    ]
                )

            self.assertEqual(result, 0)
            loader.assert_not_called()
            self.assertTrue(output_path.exists())
            with self.assertRaises(FileExistsError):
                write_run_output({}, output_path)

    def test_live_snapshot_mismatch_stops_run(self) -> None:
        expected = sample_snapshot()
        live = dict(expected)
        live["fingerprint"] = "f" * 64

        with self.assertRaisesRegex(ValueError, "does not match"):
            ensure_live_snapshot_matches(expected, live)


if __name__ == "__main__":
    unittest.main()
