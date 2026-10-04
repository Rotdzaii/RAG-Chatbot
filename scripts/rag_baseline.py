"""Offline-safe helpers for a P0 baseline run.

This module deliberately has no database, LangChain, or provider imports. The live
CLI imports those dependencies only after validation selects at least one approved
case.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol
from uuid import uuid4

from rag_snapshot import payload_fingerprint


RUN_SCHEMA_VERSION = "1.0"
HUMAN_REVIEW_PENDING = "pending_human_review"
_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


class SourceLike(Protocol):
    chunk_id: object
    document_id: object
    filename: str
    chunk_index: int
    content: str
    cosine_distance: float


class AnswerLike(Protocol):
    answer: str
    sources: list[SourceLike]


def select_cases(
    manifest: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Manifest cases are missing")
    selected: list[dict[str, object]] = []
    excluded: list[dict[str, str]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "unknown"))
        status = str(case.get("review_status", "unknown"))
        if status == "approved":
            selected.append(case)
        else:
            excluded.append(
                {
                    "case_id": case_id,
                    "review_status": status,
                    "reason": f"review_status_{status}",
                }
            )
    return selected, excluded


def build_dry_run_report(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    *,
    manifest_path: str,
) -> dict[str, object]:
    selected, excluded = select_cases(manifest)
    return _base_report(
        manifest,
        snapshot,
        manifest_path=manifest_path,
        mode="dry_run",
        selected=selected,
        excluded=excluded,
        case_results=[_dry_case(case) for case in selected],
    )


def run_live_baseline(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    *,
    manifest_path: str,
    ask: Callable[[str], AnswerLike],
    clock: Callable[[], float] = perf_counter,
) -> dict[str, object]:
    selected, excluded = select_cases(manifest)
    if not selected:
        raise ValueError("No approved cases are available for a live run")

    case_results = [
        _run_case(case, ask=ask, clock=clock) for case in selected
    ]
    report = _base_report(
        manifest,
        snapshot,
        manifest_path=manifest_path,
        mode="live",
        selected=selected,
        excluded=excluded,
        case_results=case_results,
    )
    report["retrieval_metrics"] = aggregate_retrieval_metrics(case_results)
    return report


def ensure_live_snapshot_matches(
    expected_snapshot: dict[str, object], live_snapshot: dict[str, object]
) -> None:
    expected = expected_snapshot.get("fingerprint")
    actual = live_snapshot.get("fingerprint")
    if not isinstance(expected, str) or not isinstance(actual, str):
        raise ValueError("Snapshot fingerprint is missing")
    if expected != actual:
        raise ValueError(
            "Live corpus/config fingerprint does not match the approved snapshot: "
            f"expected={expected}, actual={actual}"
        )


def case_retrieval_metrics(
    case: dict[str, object], retrieved_chunk_ids: list[str]
) -> dict[str, object]:
    metric_config = case.get("metric_applicability")
    retrieval_status = (
        metric_config.get("retrieval")
        if isinstance(metric_config, dict)
        else "not_applicable"
    )
    expected_ids = _supporting_chunk_ids(case)
    retrieved_ids = _deduplicate(retrieved_chunk_ids)

    if retrieval_status != "applicable":
        return {
            "status": retrieval_status,
            "included_in_aggregate": False,
            "expected_chunk_ids": expected_ids,
            "retrieved_chunk_ids": retrieved_ids,
        }
    if not expected_ids:
        return {
            "status": "not_applicable",
            "reason": "no_supporting_evidence",
            "included_in_aggregate": False,
            "expected_chunk_ids": [],
            "retrieved_chunk_ids": retrieved_ids,
        }

    retrieved_set = set(retrieved_ids)
    hit_ids = [chunk_id for chunk_id in expected_ids if chunk_id in retrieved_set]
    first_rank = next(
        (
            index
            for index, chunk_id in enumerate(retrieved_ids, start=1)
            if chunk_id in set(expected_ids)
        ),
        None,
    )
    recall = len(hit_ids) / len(expected_ids)
    return {
        "status": "applicable",
        "included_in_aggregate": True,
        "expected_chunk_ids": expected_ids,
        "retrieved_chunk_ids": retrieved_ids,
        "hit_chunk_ids": hit_ids,
        "recall_at_k": recall,
        "reciprocal_rank": 0.0 if first_rank is None else 1.0 / first_rank,
        "evidence_hit": bool(hit_ids),
        "all_evidence_hit": len(hit_ids) == len(expected_ids),
    }


def aggregate_retrieval_metrics(
    case_results: list[dict[str, object]],
) -> dict[str, object]:
    applicable: list[dict[str, object]] = []
    excluded_statuses: Counter[str] = Counter()
    for result in case_results:
        metrics = result.get("retrieval_metrics")
        if not isinstance(metrics, dict):
            excluded_statuses["missing"] += 1
        elif metrics.get("included_in_aggregate") is True:
            applicable.append(metrics)
        else:
            excluded_statuses[str(metrics.get("status", "unknown"))] += 1

    denominator = len(applicable)
    if denominator == 0:
        return {
            "applicable_cases": 0,
            "excluded_cases": len(case_results),
            "excluded_by_status": dict(sorted(excluded_statuses.items())),
            "recall_at_k_macro": None,
            "mrr_at_k": None,
            "evidence_hit_at_k": None,
            "all_evidence_hit_at_k": None,
        }
    return {
        "applicable_cases": denominator,
        "excluded_cases": len(case_results) - denominator,
        "excluded_by_status": dict(sorted(excluded_statuses.items())),
        "recall_at_k_macro": sum(
            float(item["recall_at_k"]) for item in applicable
        )
        / denominator,
        "mrr_at_k": sum(float(item["reciprocal_rank"]) for item in applicable)
        / denominator,
        "evidence_hit_at_k": sum(
            1 for item in applicable if item["evidence_hit"] is True
        )
        / denominator,
        "all_evidence_hit_at_k": sum(
            1 for item in applicable if item["all_evidence_hit"] is True
        )
        / denominator,
    }


def validate_citation_indices(answer: str, source_count: int) -> dict[str, object]:
    indices = [int(value) for value in _CITATION_PATTERN.findall(answer)]
    cited_indices = _deduplicate(indices)
    invalid = [index for index in cited_indices if index < 1 or index > source_count]
    return {
        "valid": not invalid,
        "cited_indices": cited_indices,
        "invalid_indices": invalid,
        "available_source_count": source_count,
    }


def write_run_output(
    report: dict[str, object], output: Path, *, overwrite: bool = False
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with output.open(mode, encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _base_report(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    *,
    manifest_path: str,
    mode: str,
    selected: list[dict[str, object]],
    excluded: list[dict[str, str]],
    case_results: list[dict[str, object]],
) -> dict[str, object]:
    payload = snapshot.get("payload")
    pipeline_config = payload.get("pipeline_config") if isinstance(payload, dict) else None
    all_cases = manifest.get("cases")
    total = len(all_cases) if isinstance(all_cases, list) else 0
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "manifest": {
            "path": manifest_path,
            "fingerprint_algorithm": "sha256",
            "fingerprint": payload_fingerprint(manifest),
        },
        "snapshot": {
            "fingerprint_algorithm": snapshot.get("fingerprint_algorithm"),
            "fingerprint": snapshot.get("fingerprint"),
        },
        "pipeline_config": pipeline_config,
        "execution_policy": {
            "entrypoint": "rag.qa.answer_question",
            "history_used": False,
            "rewritten_query": None,
            "conversation_persistence": False,
            "second_retrieval_for_observation": False,
        },
        "selection": {
            "total_cases": total,
            "selected_cases": len(selected),
            "excluded_cases": len(excluded),
            "selected_case_ids": [str(case["id"]) for case in selected],
            "excluded": excluded,
        },
        "cases": case_results,
        "human_review": {
            "groundedness": HUMAN_REVIEW_PENDING,
            "task_completion": HUMAN_REVIEW_PENDING,
            "safety": HUMAN_REVIEW_PENDING,
            "citation_support": HUMAN_REVIEW_PENDING,
        },
        "quality_scores_computed": False,
    }


def _dry_case(case: dict[str, object]) -> dict[str, object]:
    return {
        "case_id": case.get("id"),
        "question": case.get("question"),
        "history": case.get("history"),
        "history_used": False,
        "rewritten_query": None,
        "status": "not_run",
        "retrieval_metrics": {
            "status": _retrieval_status(case),
            "included_in_aggregate": False,
        },
    }


def _run_case(
    case: dict[str, object],
    *,
    ask: Callable[[str], AnswerLike],
    clock: Callable[[], float],
) -> dict[str, object]:
    question = str(case["question"])
    result: dict[str, object] = {
        "case_id": case.get("id"),
        "question": question,
        "history": case.get("history"),
        "history_used": False,
        "rewritten_query": None,
        "answer": None,
        "retrieved_chunks": [],
        "sources": [],
        "latency_ms": None,
        "error": None,
        "citation_index_validation": None,
        "human_review": {
            "groundedness": HUMAN_REVIEW_PENDING,
            "task_completion": HUMAN_REVIEW_PENDING,
            "safety": HUMAN_REVIEW_PENDING,
            "citation_support": HUMAN_REVIEW_PENDING,
        },
    }
    started = clock()
    try:
        qa_result = ask(question)
        sources = [_serialize_source(source, index) for index, source in enumerate(qa_result.sources, start=1)]
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
                "answer": qa_result.answer,
                "retrieved_chunks": retrieved_chunks,
                "sources": sources,
                "citation_index_validation": validate_citation_indices(
                    qa_result.answer, len(sources)
                ),
            }
        )
    except Exception as error:
        result.update(
            {
                "status": "error",
                "error": {
                    "type": type(error).__name__,
                    "message": "Case execution failed",
                },
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

    chunk_ids = [
        str(chunk["chunk_id"])
        for chunk in result["retrieved_chunks"]
        if isinstance(chunk, dict)
    ]
    result["retrieval_metrics"] = case_retrieval_metrics(case, chunk_ids)
    return result


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


def _supporting_chunk_ids(case: dict[str, object]) -> list[str]:
    evidence = case.get("evidence")
    if not isinstance(evidence, list):
        return []
    return _deduplicate(
        str(item["chunk_id"])
        for item in evidence
        if isinstance(item, dict)
        and item.get("kind") == "supporting"
        and isinstance(item.get("chunk_id"), str)
    )


def _retrieval_status(case: dict[str, object]) -> str:
    metrics = case.get("metric_applicability")
    if not isinstance(metrics, dict):
        return "not_applicable"
    return str(metrics.get("retrieval", "not_applicable"))


def _deduplicate(values):
    return list(dict.fromkeys(values))
