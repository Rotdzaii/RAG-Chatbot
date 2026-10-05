"""Offline-safe helpers for the P1 multi-turn RAG evaluation runner."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter, sleep
from typing import Callable, Protocol
from uuid import uuid4

from rag_baseline import (
    HUMAN_REVIEW_PENDING,
    aggregate_retrieval_metrics,
    case_retrieval_metrics,
    select_cases,
    validate_citation_indices,
)
from rag_snapshot import payload_fingerprint


RUN_SCHEMA_VERSION = "1.0"
STABLE_PIPELINE_SECTIONS = (
    "extraction",
    "chunking",
    "embedding",
    "retrieval",
)
VECTOR_VERIFICATION_SCOPE = (
    "Snapshot compatibility checks embedding presence and dimension metadata only; "
    "the snapshot does not contain full vectors, so vector values are not verified."
)


class SourceLike(Protocol):
    chunk_id: object
    document_id: object
    filename: str
    chunk_index: int
    content: str
    cosine_distance: float


class MultiTurnAnswerLike(Protocol):
    answer: str
    sources: list[SourceLike]
    history_used: bool
    query_processing_action: str
    query_processing_elapsed_ms: float
    rewritten_query: str | None


def corpus_fingerprint(snapshot: dict[str, object]) -> str:
    payload = _snapshot_payload(snapshot)
    documents = payload.get("documents")
    chunks = payload.get("chunks")
    if not isinstance(documents, list) or not isinstance(chunks, list):
        raise ValueError("Snapshot documents/chunks are missing")
    return payload_fingerprint({"documents": documents, "chunks": chunks})


def stable_pipeline_config_fingerprint(snapshot: dict[str, object]) -> str:
    config = _pipeline_config(snapshot)
    stable_config: dict[str, object] = {}
    for section in STABLE_PIPELINE_SECTIONS:
        if section not in config:
            raise ValueError(f"Snapshot pipeline_config.{section} is missing")
        stable_config[section] = config[section]
    return payload_fingerprint(stable_config)


def ensure_live_compatibility(
    expected_snapshot: dict[str, object],
    live_snapshot: dict[str, object],
) -> dict[str, object]:
    expected_corpus = corpus_fingerprint(expected_snapshot)
    live_corpus = corpus_fingerprint(live_snapshot)
    if expected_corpus != live_corpus:
        raise ValueError(
            "Live corpus fingerprint does not match the approved snapshot: "
            f"expected={expected_corpus}, actual={live_corpus}"
        )

    expected_config = stable_pipeline_config_fingerprint(expected_snapshot)
    live_config = stable_pipeline_config_fingerprint(live_snapshot)
    if expected_config != live_config:
        raise ValueError(
            "Live extraction/chunking/embedding/retrieval configuration does not "
            "match P0: "
            f"expected={expected_config}, actual={live_config}"
        )

    return {
        "status": "matched",
        "fingerprint_algorithm": "sha256",
        "corpus": {
            "expected": expected_corpus,
            "live": live_corpus,
            "matched": True,
        },
        "stable_pipeline_config": {
            "sections": list(STABLE_PIPELINE_SECTIONS),
            "expected": expected_config,
            "live": live_config,
            "matched": True,
        },
        "full_vector_verification": False,
        "vector_verification_scope": VECTOR_VERIFICATION_SCOPE,
    }


def build_dry_run_report(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    *,
    manifest_path: str,
    query_processing_config: dict[str, object],
    case_id: str | None = None,
) -> dict[str, object]:
    selected, excluded = select_eval_cases(manifest, case_id=case_id)
    return _base_report(
        manifest,
        snapshot,
        manifest_path=manifest_path,
        mode="dry_run",
        query_processing_config=query_processing_config,
        selected=selected,
        excluded=excluded,
        case_results=[_dry_case(case) for case in selected],
        live_verification={
            "status": "not_run",
            "reason": "dry_run_does_not_access_database",
            "expected_corpus_fingerprint": corpus_fingerprint(snapshot),
            "expected_stable_pipeline_config_fingerprint": (
                stable_pipeline_config_fingerprint(snapshot)
            ),
            "full_vector_verification": False,
            "vector_verification_scope": VECTOR_VERIFICATION_SCOPE,
        },
        requested_case_id=case_id,
    )


def run_live_multiturn_eval(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    *,
    manifest_path: str,
    query_processing_config: dict[str, object],
    live_verification: dict[str, object],
    ask: Callable[[str, list[dict[str, str]]], MultiTurnAnswerLike],
    clock: Callable[[], float] = perf_counter,
    sleeper: Callable[[float], None] = sleep,
    case_interval_seconds: float = 0.0,
    case_id: str | None = None,
) -> dict[str, object]:
    if case_interval_seconds < 0:
        raise ValueError("case_interval_seconds must not be negative")
    selected, excluded = select_eval_cases(manifest, case_id=case_id)
    if not selected:
        raise ValueError("No approved cases are available for a live run")

    case_results: list[dict[str, object]] = []
    incomplete_reason: str | None = None
    for index, case in enumerate(selected):
        if index > 0 and case_interval_seconds > 0:
            sleeper(case_interval_seconds)
        result = _run_case(case, ask=ask, clock=clock)
        case_results.append(result)
        if _is_rate_limit_failure(result):
            incomplete_reason = "stopped_after_provider_rate_limit"
            case_results.extend(
                _not_run_case(
                    remaining,
                    reason=incomplete_reason,
                )
                for remaining in selected[index + 1 :]
            )
            break

    report = _base_report(
        manifest,
        snapshot,
        manifest_path=manifest_path,
        mode="live",
        query_processing_config=query_processing_config,
        selected=selected,
        excluded=excluded,
        case_results=case_results,
        live_verification=live_verification,
        requested_case_id=case_id,
        case_interval_seconds=case_interval_seconds,
    )
    run_complete = incomplete_reason is None
    report["run_status"] = "complete" if run_complete else "incomplete"
    report["incomplete_reason"] = incomplete_reason
    executed_results = [
        result for result in case_results if result.get("status") != "not_run"
    ]
    aggregate = aggregate_retrieval_metrics(executed_results)
    if run_complete:
        report["retrieval_metrics"] = aggregate
    else:
        report["retrieval_metrics"] = {
            "status": "incomplete_run",
            "represents_full_selected_run": False,
            "reason": incomplete_reason,
            "executed_cases": len(executed_results),
            "selected_cases": len(selected),
            "partial_metrics": aggregate,
        }
    report["execution"] = execution_summary(case_results)
    report["execution"]["run_complete"] = run_complete
    return report


def select_eval_cases(
    manifest: dict[str, object], *, case_id: str | None = None
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    if case_id is None:
        return select_cases(manifest)

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Manifest cases are missing")
    matching = [
        case
        for case in cases
        if isinstance(case, dict) and str(case.get("id")) == case_id
    ]
    if not matching:
        raise ValueError(f"Unknown case ID: {case_id}")

    filtered_manifest = {"cases": matching}
    return select_cases(filtered_manifest)


def execution_summary(case_results: list[dict[str, object]]) -> dict[str, object]:
    statuses = Counter(str(result.get("status", "unknown")) for result in case_results)
    errors_by_stage: Counter[str] = Counter()
    error_case_ids_by_stage: dict[str, list[str]] = {}
    failures_in_retrieval_denominator = 0
    for result in case_results:
        if result.get("status") != "error":
            continue
        error = result.get("error")
        stage = (
            str(error.get("error_stage", "unknown"))
            if isinstance(error, dict)
            else "unknown"
        )
        errors_by_stage[stage] += 1
        error_case_ids_by_stage.setdefault(stage, []).append(
            str(result.get("case_id", "unknown"))
        )
        metrics = result.get("retrieval_metrics")
        if isinstance(metrics, dict) and metrics.get("included_in_aggregate") is True:
            failures_in_retrieval_denominator += 1

    return {
        "total_cases": len(case_results),
        "attempted_cases": statuses.get("completed", 0) + statuses.get("error", 0),
        "completed_cases": statuses.get("completed", 0),
        "failed_cases": statuses.get("error", 0),
        "error_cases": statuses.get("error", 0),
        "not_run_cases": statuses.get("not_run", 0),
        "failed_case_ids": [
            str(result.get("case_id", "unknown"))
            for result in case_results
            if result.get("status") == "error"
        ],
        "not_run_case_ids": [
            str(result.get("case_id", "unknown"))
            for result in case_results
            if result.get("status") == "not_run"
        ],
        "errors_by_stage": dict(sorted(errors_by_stage.items())),
        "error_case_ids_by_stage": dict(sorted(error_case_ids_by_stage.items())),
        "execution_failures_in_retrieval_denominator": (
            failures_in_retrieval_denominator
        ),
    }


def _base_report(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    *,
    manifest_path: str,
    mode: str,
    query_processing_config: dict[str, object],
    selected: list[dict[str, object]],
    excluded: list[dict[str, str]],
    case_results: list[dict[str, object]],
    live_verification: dict[str, object],
    requested_case_id: str | None,
    case_interval_seconds: float = 0.0,
) -> dict[str, object]:
    baseline_config = _pipeline_config(snapshot)
    p1_config = deepcopy(baseline_config)
    p1_config["query_processing"] = deepcopy(query_processing_config)
    report = {
        "schema_version": RUN_SCHEMA_VERSION,
        "evaluation_phase": "P1.2",
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "run_status": "not_run" if mode == "dry_run" else "complete",
        "incomplete_reason": None,
        "manifest": {
            "path": manifest_path,
            "fingerprint_algorithm": "sha256",
            "fingerprint": payload_fingerprint(manifest),
        },
        "snapshot": {
            "fingerprint_algorithm": snapshot.get("fingerprint_algorithm"),
            "fingerprint": snapshot.get("fingerprint"),
            "corpus_fingerprint_algorithm": "sha256",
            "corpus_fingerprint": corpus_fingerprint(snapshot),
        },
        "live_compatibility": live_verification,
        "pipeline_config": p1_config,
        "pipeline_config_fingerprint": payload_fingerprint(p1_config),
        "p0_to_p1": {
            "p0_query_processing": deepcopy(
                baseline_config.get("query_processing")
            ),
            "p1_query_processing": deepcopy(query_processing_config),
            "unchanged_config_sections_verified_before_live": list(
                STABLE_PIPELINE_SECTIONS
            ),
            "differences": [
                "History fixtures are supplied to answer_question for each case.",
                "The query processor chooses search or clarify once per case.",
                "Search uses the actual standalone query for retrieval and generation.",
                "Clarify skips retrieval and grounded-answer generation.",
            ],
        },
        "execution_policy": {
            "entrypoint": "rag.qa.answer_question",
            "original_question_preserved": True,
            "history_source": "approved_manifest_fixture",
            "conversation_persistence": False,
            "query_processor_invocations_per_case": 1,
            "second_rewrite_for_observation": False,
            "second_retrieval_for_observation": False,
            "case_interval_seconds": case_interval_seconds,
            "case_interval_applies_between_cases_only": True,
        },
        "selection": {
            "total_cases": len(selected) + len(excluded),
            "selected_cases": len(selected),
            "excluded_cases": len(excluded),
            "requested_case_id": requested_case_id,
            "selected_case_ids": [str(case["id"]) for case in selected],
            "excluded": excluded,
        },
        "cases": case_results,
        "human_review": _pending_human_review(),
        "quality_scores_computed": False,
    }
    report["execution"] = execution_summary(case_results)
    return report


def _dry_case(case: dict[str, object]) -> dict[str, object]:
    return {
        "case_id": case.get("id"),
        "question": case.get("question"),
        "history": _case_history(case),
        "action": None,
        "rewritten_query": None,
        "history_used": None,
        "query_processing_latency_ms": None,
        "latency_ms": None,
        "answer": None,
        "retrieved_chunks": [],
        "sources": [],
        "citation_index_validation": None,
        "error": None,
        "status": "not_run",
        "retrieval_metrics": {
            "status": _retrieval_status(case),
            "included_in_aggregate": False,
        },
        "human_review": _pending_human_review(),
    }


def _not_run_case(
    case: dict[str, object], *, reason: str
) -> dict[str, object]:
    result = _dry_case(case)
    result["not_run_reason"] = reason
    metrics = result["retrieval_metrics"]
    if isinstance(metrics, dict):
        metrics["reason"] = reason
    return result


def _is_rate_limit_failure(result: dict[str, object]) -> bool:
    if result.get("status") != "error":
        return False
    error = result.get("error")
    return (
        isinstance(error, dict)
        and error.get("provider_error_kind") == "rate_limit"
    )


def _run_case(
    case: dict[str, object],
    *,
    ask: Callable[[str, list[dict[str, str]]], MultiTurnAnswerLike],
    clock: Callable[[], float],
) -> dict[str, object]:
    question = str(case["question"])
    history = _case_history(case)
    result: dict[str, object] = {
        "case_id": case.get("id"),
        "question": question,
        "history": history,
        "action": None,
        "rewritten_query": None,
        "history_used": None,
        "query_processing_latency_ms": None,
        "latency_ms": None,
        "answer": None,
        "retrieved_chunks": [],
        "sources": [],
        "citation_index_validation": None,
        "error": None,
        "human_review": _pending_human_review(),
    }
    started = clock()
    caught_error: Exception | None = None
    try:
        qa_result = ask(question, history)
        sources = [
            _serialize_source(source, index)
            for index, source in enumerate(qa_result.sources, start=1)
        ]
        retrieved_chunks = [
            {
                "chunk_id": source["chunk_id"],
                "document_id": source["document_id"],
                "filename": source["filename"],
                "chunk_index": source["chunk_index"],
                "content": source["content"],
                "cosine_distance": source["cosine_distance"],
            }
            for source in sources
        ]
        result.update(
            {
                "status": "completed",
                "action": qa_result.query_processing_action,
                "rewritten_query": qa_result.rewritten_query,
                "history_used": qa_result.history_used,
                "query_processing_latency_ms": round(
                    float(qa_result.query_processing_elapsed_ms), 3
                ),
                "answer": qa_result.answer,
                "retrieved_chunks": retrieved_chunks,
                "sources": sources,
                "citation_index_validation": validate_citation_indices(
                    qa_result.answer, len(sources)
                ),
            }
        )
    except Exception as error:
        caught_error = error
        result.update(
            {
                "status": "error",
                "citation_index_validation": {
                    "valid": False,
                    "reason": "case_execution_failed",
                    "cited_indices": [],
                    "invalid_indices": [],
                    "available_source_count": 0,
                },
            }
        )
    finally:
        result["latency_ms"] = round((clock() - started) * 1000, 3)

    if caught_error is not None:
        result["error"] = _safe_error_metadata(
            caught_error,
            fallback_elapsed_ms=float(result["latency_ms"]),
        )

    chunk_ids = [
        str(chunk["chunk_id"])
        for chunk in result["retrieved_chunks"]
        if isinstance(chunk, dict)
    ]
    result["retrieval_metrics"] = case_retrieval_metrics(case, chunk_ids)
    return result


def _safe_error_metadata(
    error: Exception, *, fallback_elapsed_ms: float
) -> dict[str, object]:
    stage = getattr(error, "error_stage", "unknown")
    if not isinstance(stage, str) or not stage:
        stage = "unknown"

    cause_type = getattr(error, "cause_type", None)
    if not isinstance(cause_type, str) or not cause_type:
        cause_type = type(error).__name__

    category = getattr(error, "category", "unknown")
    if category not in {"provider", "timeout", "schema_validation", "unknown"}:
        category = "unknown"

    error_kind = getattr(error, "provider_error_kind", None)
    if error_kind not in {"rate_limit", None}:
        error_kind = None

    status_code = getattr(error, "provider_status_code", None)
    if not (
        isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and 100 <= status_code <= 599
    ):
        status_code = None

    elapsed_ms = getattr(error, "elapsed_ms", None)
    if not isinstance(elapsed_ms, (int, float)) or isinstance(elapsed_ms, bool):
        elapsed_ms = fallback_elapsed_ms

    return {
        "type": type(error).__name__,
        "message": "Case execution failed",
        "error_stage": stage,
        "cause_type": cause_type,
        "provider_status_code": status_code,
        "category": category,
        "provider_error_kind": error_kind,
        "elapsed_ms": round(float(elapsed_ms), 3),
    }


def _case_history(case: dict[str, object]) -> list[dict[str, str]]:
    history = case.get("history")
    if not isinstance(history, list):
        return []
    return [
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in history
        if isinstance(message, dict)
        and isinstance(message.get("role"), str)
        and isinstance(message.get("content"), str)
    ]


def _serialize_source(source: SourceLike, citation_index: int) -> dict[str, object]:
    return {
        "citation_index": citation_index,
        "chunk_id": str(source.chunk_id),
        "document_id": str(source.document_id),
        "filename": str(source.filename),
        "chunk_index": int(source.chunk_index),
        "content": str(source.content),
        "cosine_distance": float(source.cosine_distance),
    }


def _snapshot_payload(snapshot: dict[str, object]) -> dict[str, object]:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Snapshot payload is missing")
    return payload


def _pipeline_config(snapshot: dict[str, object]) -> dict[str, object]:
    config = _snapshot_payload(snapshot).get("pipeline_config")
    if not isinstance(config, dict):
        raise ValueError("Snapshot pipeline_config is missing")
    return config


def _retrieval_status(case: dict[str, object]) -> str:
    metrics = case.get("metric_applicability")
    if not isinstance(metrics, dict):
        return "not_applicable"
    return str(metrics.get("retrieval", "not_applicable"))


def _pending_human_review() -> dict[str, str]:
    return {
        "groundedness": HUMAN_REVIEW_PENDING,
        "task_completion": HUMAN_REVIEW_PENDING,
        "safety": HUMAN_REVIEW_PENDING,
        "citation_support": HUMAN_REVIEW_PENDING,
    }
