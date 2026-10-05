from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from langchain_google_genai.chat_models import GoogleRateLimitError


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_rag_multiturn_eval as multiturn_cli  # noqa: E402
from rag.query_contract import query_processing_config  # noqa: E402
from rag.query_processing import QueryProcessingError  # noqa: E402
from rag.provider_errors import ProviderCallError  # noqa: E402
from rag_multiturn_eval import (  # noqa: E402
    build_dry_run_report,
    corpus_fingerprint,
    ensure_live_compatibility,
    run_live_multiturn_eval,
    select_eval_cases,
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
    case["reviewed_at"] = "2026-10-04T09:00:00+07:00"
    case["metric_applicability"]["retrieval"] = "applicable"
    case["metric_applicability"]["answer_quality"] = "applicable"
    case["history"] = [
        {"role": "user", "content": "Ngành Marketing có những chuyên ngành nào?"},
        {"role": "assistant", "content": "Ngành Marketing có bốn chuyên ngành."},
    ]
    metadata = case.get("metadata")
    assert isinstance(metadata, dict)
    metadata["history_fixture"] = True
    return manifest, snapshot


def approved_manifest_with_case_count(
    count: int,
) -> tuple[dict[str, object], dict[str, object]]:
    manifest, snapshot = approved_manifest()
    first = manifest["cases"][0]
    manifest["cases"] = []
    for number in range(1, count + 1):
        case = copy.deepcopy(first)
        case["id"] = f"TEST-P1-{number:03d}"
        case["question"] = f"Question {number}?"
        manifest["cases"].append(case)
    return manifest, snapshot


def answer_result(
    *,
    evidence_id: str,
    action: str = "search",
    rewritten_query: str | None = "Ngành Marketing học bao lâu?",
    sources: bool = True,
) -> SimpleNamespace:
    result_sources = []
    if sources:
        result_sources.append(
            SimpleNamespace(
                chunk_id=evidence_id,
                document_id="11111111-1111-4111-8111-111111111111",
                filename="marketing.pdf",
                chunk_index=0,
                content="Thời gian đào tạo 3.5 năm.",
                cosine_distance=0.1,
            )
        )
    return SimpleNamespace(
        answer=(
            "Thời gian đào tạo là 3.5 năm [1]."
            if action == "search"
            else "Bạn đang muốn hỏi về ngành nào?"
        ),
        sources=result_sources,
        history_used=True,
        query_processing_action=action,
        query_processing_elapsed_ms=12.3456,
        rewritten_query=rewritten_query,
    )


class RagMultiturnEvalTests(unittest.TestCase):
    def test_live_run_passes_original_question_and_history_once(self) -> None:
        manifest, snapshot = approved_manifest()
        case = manifest["cases"][0]
        evidence_id = case["evidence"][0]["chunk_id"]
        ask = Mock(return_value=answer_result(evidence_id=evidence_id))
        times = iter((2.0, 2.08))

        report = run_live_multiturn_eval(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
            live_verification={"status": "matched"},
            ask=ask,
            clock=lambda: next(times),
        )

        ask.assert_called_once_with(case["question"], case["history"])
        result = report["cases"][0]
        self.assertEqual(result["action"], "search")
        self.assertEqual(
            result["rewritten_query"], "Ngành Marketing học bao lâu?"
        )
        self.assertTrue(result["history_used"])
        self.assertEqual(result["query_processing_latency_ms"], 12.346)
        self.assertEqual(result["latency_ms"], 80.0)
        self.assertEqual(result["retrieved_chunks"][0]["chunk_id"], evidence_id)
        self.assertTrue(result["citation_index_validation"]["valid"])
        self.assertEqual(report["retrieval_metrics"]["recall_at_k_macro"], 1.0)
        self.assertEqual(
            report["execution_policy"]["query_processor_invocations_per_case"],
            1,
        )
        self.assertFalse(
            report["execution_policy"]["second_retrieval_for_observation"]
        )

    def test_clarify_keeps_retrieval_applicable_case_in_denominator(self) -> None:
        manifest, snapshot = approved_manifest()
        evidence_id = manifest["cases"][0]["evidence"][0]["chunk_id"]

        report = run_live_multiturn_eval(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
            live_verification={"status": "matched"},
            ask=lambda _question, _history: answer_result(
                evidence_id=evidence_id,
                action="clarify",
                rewritten_query=None,
                sources=False,
            ),
        )

        case = report["cases"][0]
        self.assertEqual(case["action"], "clarify")
        self.assertIsNone(case["rewritten_query"])
        self.assertEqual(case["retrieved_chunks"], [])
        self.assertTrue(case["retrieval_metrics"]["included_in_aggregate"])
        self.assertEqual(case["retrieval_metrics"]["recall_at_k"], 0.0)
        self.assertEqual(report["retrieval_metrics"]["applicable_cases"], 1)
        self.assertEqual(report["retrieval_metrics"]["excluded_cases"], 0)

    def test_uses_separate_canonical_corpus_and_stable_config_fingerprints(self) -> None:
        expected = sample_snapshot()
        live = copy.deepcopy(expected)
        live["payload"]["pipeline_config"]["query_processing"] = (
            query_processing_config()
        )

        verification = ensure_live_compatibility(expected, live)

        self.assertEqual(corpus_fingerprint(expected), corpus_fingerprint(live))
        self.assertTrue(verification["corpus"]["matched"])
        self.assertTrue(verification["stable_pipeline_config"]["matched"])
        self.assertFalse(verification["full_vector_verification"])
        self.assertIn("does not contain full vectors", verification["vector_verification_scope"])

    def test_corpus_and_stable_config_mismatches_stop_live_run(self) -> None:
        expected = sample_snapshot()
        changed_corpus = copy.deepcopy(expected)
        changed_corpus["payload"]["chunks"][0]["content"] = "changed"

        with self.assertRaisesRegex(ValueError, "corpus fingerprint"):
            ensure_live_compatibility(expected, changed_corpus)

        changed_config = copy.deepcopy(expected)
        changed_config["payload"]["pipeline_config"]["retrieval"] = {
            "max_cosine_distance": 0.9
        }
        with self.assertRaisesRegex(ValueError, "does not match P0"):
            ensure_live_compatibility(expected, changed_config)

    def test_error_is_sanitized_and_metrics_still_use_case_applicability(self) -> None:
        manifest, snapshot = approved_manifest()
        provider_error = QueryProcessingError(
            cause_type="ProviderFailure",
            category="provider",
            provider_status_code=429,
            elapsed_ms=123.456,
        )
        provider_error.__cause__ = RuntimeError(
            "secret body https://provider.invalid?key=secret"
        )

        report = run_live_multiturn_eval(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
            live_verification={"status": "matched"},
            ask=lambda _question, _history: (_ for _ in ()).throw(
                provider_error
            ),
        )

        case = report["cases"][0]
        self.assertEqual(case["status"], "error")
        self.assertEqual(case["error"]["type"], "QueryProcessingError")
        self.assertEqual(case["error"]["message"], "Case execution failed")
        self.assertEqual(case["error"]["error_stage"], "query_processing")
        self.assertEqual(case["error"]["cause_type"], "ProviderFailure")
        self.assertEqual(case["error"]["provider_status_code"], 429)
        self.assertEqual(case["error"]["category"], "provider")
        self.assertEqual(case["error"]["elapsed_ms"], 123.456)
        serialized = json.dumps(report)
        self.assertNotIn("secret body", serialized)
        self.assertNotIn("provider.invalid", serialized)
        self.assertNotIn("key=secret", serialized)
        self.assertTrue(case["retrieval_metrics"]["included_in_aggregate"])
        self.assertEqual(report["execution"]["completed_cases"], 0)
        self.assertEqual(report["execution"]["error_cases"], 1)
        self.assertEqual(
            report["execution"]["errors_by_stage"], {"query_processing": 1}
        )
        self.assertEqual(
            report["execution"]["execution_failures_in_retrieval_denominator"],
            1,
        )

    def test_dry_run_writes_metadata_without_loading_live_dependencies(self) -> None:
        manifest, snapshot = approved_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            snapshot_path = root / "snapshot.json"
            output_path = root / "run.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            with patch.object(multiturn_cli, "_load_live_dependencies") as loader:
                result = multiturn_cli.main(
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
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "dry_run")
            self.assertEqual(report["selection"]["selected_cases"], 1)
            self.assertEqual(report["live_compatibility"]["status"], "not_run")
            self.assertIsNone(report["cases"][0]["action"])
            prompt_hash = report["pipeline_config"]["query_processing"][
                "system_instruction_sha256"
            ]
            self.assertEqual(len(prompt_hash), 64)
            self.assertFalse(report["quality_scores_computed"])

    def test_build_dry_run_preserves_pending_human_review(self) -> None:
        manifest, snapshot = approved_manifest()

        report = build_dry_run_report(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
        )

        self.assertEqual(
            set(report["human_review"].values()),
            {"pending_human_review"},
        )
        self.assertFalse(report["quality_scores_computed"])

    def test_case_filter_selects_exact_case_and_rejects_unknown_id(self) -> None:
        manifest, snapshot = approved_manifest()
        case_id = str(manifest["cases"][0]["id"])

        selected, excluded = select_eval_cases(manifest, case_id=case_id)
        report = build_dry_run_report(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
            case_id=case_id,
        )

        self.assertEqual([case["id"] for case in selected], [case_id])
        self.assertEqual(excluded, [])
        self.assertEqual(report["selection"]["total_cases"], 1)
        self.assertEqual(report["selection"]["requested_case_id"], case_id)
        with self.assertRaisesRegex(ValueError, "Unknown case ID"):
            select_eval_cases(manifest, case_id="MKT-P0-999")

    def test_live_cli_writes_error_artifact_before_nonzero_exit(self) -> None:
        manifest, snapshot = approved_manifest()
        case_id = str(manifest["cases"][0]["id"])
        provider_error = GoogleRateLimitError(
            "secret provider response https://provider.invalid?key=secret"
        )
        failure = ProviderCallError(
            error_stage="generation",
            cause_type="GoogleRateLimitError",
            provider_error_kind="rate_limit",
            provider_status_code=None,
            elapsed_ms=50.0,
        )
        failure.__cause__ = provider_error
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = object()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            snapshot_path = root / "snapshot.json"
            output_path = root / "diagnostic.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            with patch.object(
                multiturn_cli,
                "_load_live_dependencies",
                return_value=(
                    lambda: snapshot,
                    session_factory,
                    Mock(side_effect=failure),
                    lambda **message: message,
                ),
            ):
                result = multiturn_cli.main(
                    [
                        str(manifest_path),
                        "--snapshot",
                        str(snapshot_path),
                        "--output",
                        str(output_path),
                        "--case-id",
                        case_id,
                    ]
                )

            self.assertEqual(result, 3)
            self.assertTrue(output_path.exists())
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["selection"]["selected_case_ids"], [case_id])
            self.assertEqual(report["execution"]["error_cases"], 1)
            self.assertEqual(report["run_status"], "incomplete")
            self.assertEqual(
                report["execution"]["errors_by_stage"],
                {"generation": 1},
            )
            error = report["cases"][0]["error"]
            self.assertEqual(error["category"], "provider")
            self.assertEqual(error["provider_error_kind"], "rate_limit")
            self.assertEqual(error["cause_type"], "GoogleRateLimitError")
            self.assertIsNone(error["provider_status_code"])
            serialized = json.dumps(report)
            self.assertNotIn("secret provider response", serialized)
            self.assertNotIn("provider.invalid", serialized)
            self.assertNotIn("key=secret", serialized)

    def test_existing_output_stops_before_loading_any_live_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "existing.json"
            output_path.write_text("existing artifact", encoding="utf-8")

            with (
                patch.object(multiturn_cli, "read_json") as read_manifest,
                patch.object(multiturn_cli, "read_snapshot") as read_snapshot,
                patch.object(
                    multiturn_cli, "_load_query_processing_config"
                ) as load_config,
                patch.object(
                    multiturn_cli, "_load_live_dependencies"
                ) as load_live,
            ):
                result = multiturn_cli.main(
                    [
                        "missing-manifest.json",
                        "--snapshot",
                        "missing-snapshot.json",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(result, 1)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"), "existing artifact"
            )
            read_manifest.assert_not_called()
            read_snapshot.assert_not_called()
            load_config.assert_not_called()
            load_live.assert_not_called()

    def test_rate_limit_stops_run_and_marks_remaining_cases_not_run(self) -> None:
        manifest, snapshot = approved_manifest_with_case_count(3)
        evidence_id = manifest["cases"][0]["evidence"][0]["chunk_id"]
        rate_limit = ProviderCallError(
            error_stage="generation",
            cause_type="GoogleRateLimitError",
            provider_error_kind="rate_limit",
            provider_status_code=None,
            elapsed_ms=50.0,
        )
        ask = Mock(
            side_effect=[
                answer_result(evidence_id=evidence_id),
                rate_limit,
                answer_result(evidence_id=evidence_id),
            ]
        )

        report = run_live_multiturn_eval(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
            live_verification={"status": "matched"},
            ask=ask,
        )

        self.assertEqual(ask.call_count, 2)
        self.assertEqual(
            [case["status"] for case in report["cases"]],
            ["completed", "error", "not_run"],
        )
        self.assertEqual(
            report["cases"][2]["not_run_reason"],
            "stopped_after_provider_rate_limit",
        )
        self.assertEqual(report["run_status"], "incomplete")
        self.assertEqual(report["execution"]["attempted_cases"], 2)
        self.assertEqual(report["execution"]["failed_cases"], 1)
        self.assertEqual(report["execution"]["not_run_cases"], 1)
        self.assertEqual(
            report["execution"]["not_run_case_ids"], ["TEST-P1-003"]
        )
        metrics = report["retrieval_metrics"]
        self.assertEqual(metrics["status"], "incomplete_run")
        self.assertFalse(metrics["represents_full_selected_run"])
        self.assertNotIn("recall_at_k_macro", metrics)
        self.assertEqual(metrics["partial_metrics"]["applicable_cases"], 2)

    def test_case_interval_runs_only_between_cases_with_fake_clock(self) -> None:
        manifest, snapshot = approved_manifest_with_case_count(3)
        evidence_id = manifest["cases"][0]["evidence"][0]["chunk_id"]
        now = [10.0]
        sleeps: list[float] = []

        def clock() -> float:
            return now[0]

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        def ask(_question: str, _history: list[dict[str, str]]) -> SimpleNamespace:
            now[0] += 0.01
            return answer_result(evidence_id=evidence_id)

        report = run_live_multiturn_eval(
            manifest,
            snapshot,
            manifest_path="evals/cases/test.json",
            query_processing_config=query_processing_config(),
            live_verification={"status": "matched"},
            ask=ask,
            clock=clock,
            sleeper=sleeper,
            case_interval_seconds=2.5,
        )

        self.assertEqual(sleeps, [2.5, 2.5])
        self.assertEqual(
            [case["latency_ms"] for case in report["cases"]],
            [10.0, 10.0, 10.0],
        )
        self.assertEqual(report["run_status"], "complete")
        self.assertTrue(report["execution"]["run_complete"])
        self.assertEqual(
            report["execution_policy"]["case_interval_seconds"], 2.5
        )

    def test_cli_rejects_unknown_case_id_without_writing_output(self) -> None:
        manifest, snapshot = approved_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            snapshot_path = root / "snapshot.json"
            output_path = root / "diagnostic.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            result = multiturn_cli.main(
                [
                    str(manifest_path),
                    "--snapshot",
                    str(snapshot_path),
                    "--output",
                    str(output_path),
                    "--dry-run",
                    "--case-id",
                    "MKT-P0-999",
                ]
            )

            self.assertEqual(result, 1)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
