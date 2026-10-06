"""Offline-safe P3 retrieval analysis; this module never imports the provider."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Callable, Protocol
from uuid import uuid4

from rag_baseline import aggregate_retrieval_metrics, case_retrieval_metrics, select_cases
from rag_snapshot import payload_fingerprint


THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40)
TOP_K_VALUES = (3, 5, 10)
DIRECT_QUERY_TYPES = frozenset({"standalone", "paraphrase", "typo"})


class Candidate(Protocol):
    chunk_id: object
    document_id: object
    filename: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    cosine_distance: float


def select_direct_cases(
    manifest: dict[str, object], case_id: str | None = None
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    approved, excluded = select_cases(manifest)
    all_cases = manifest.get("cases", [])
    if case_id is not None and not any(
        isinstance(case, dict) and case.get("id") == case_id for case in all_cases
    ):
        raise ValueError(f"Unknown case ID: {case_id}")
    selected: list[dict[str, object]] = []
    for case in approved:
        name = str(case["id"])
        if case_id is not None and name != case_id:
            continue
        applicability = case.get("metric_applicability")
        if not isinstance(applicability, dict) or applicability.get("retrieval") != "applicable":
            reason = "retrieval_not_applicable"
        elif case.get("query_type") not in DIRECT_QUERY_TYPES or case.get("history"):
            reason = "requires_query_processing_or_history"
        else:
            selected.append(case)
            continue
        excluded.append({"case_id": name, "reason": reason})
    return selected, excluded


def _row(case: dict[str, object], candidates: list[Candidate]) -> dict[str, object]:
    scenarios: list[dict[str, object]] = []
    for threshold in THRESHOLDS:
        eligible = [item for item in candidates if item.cosine_distance <= threshold]
        for top_k in TOP_K_VALUES:
            ids = [str(item.chunk_id) for item in eligible[:top_k]]
            scenarios.append({
                "threshold": threshold,
                "top_k": top_k,
                "retrieval_metrics": case_retrieval_metrics(case, ids),
            })
    return {
        "case_id": case["id"],
        "status": "completed",
        "candidates": [
            {
                "chunk_id": str(item.chunk_id),
                "document_id": str(item.document_id),
                "filename": item.filename,
                "chunk_index": item.chunk_index,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "cosine_distance": item.cosine_distance,
            }
            for item in candidates
        ],
        "scenarios": scenarios,
    }


def build_report(
    manifest: dict[str, object], snapshot: dict[str, object], *,
    case_id: str | None = None,
    fetch: Callable[[str], list[Candidate]] | None = None,
    clock: Callable[[], float] = perf_counter,
) -> dict[str, object]:
    selected, excluded = select_direct_cases(manifest, case_id)
    rows: list[dict[str, object]] = []
    for index, case in enumerate(selected):
        if fetch is None:
            rows.append({"case_id": case["id"], "status": "not_run"})
            continue
        started = clock()
        try:
            row = _row(case, fetch(str(case["question"])))
        except Exception as error:
            # Stop on every provider/DB error. Never export the exception body,
            # which may contain credentials, URLs, or the original query.
            rows.append({
                "case_id": case["id"], "status": "error",
                "error_type": type(error).__name__,
                "latency_ms": round((clock() - started) * 1000, 3),
            })
            rows.extend({"case_id": remaining["id"], "status": "not_run",
                         "reason": "stopped_after_error"} for remaining in selected[index + 1:])
            break
        row["latency_ms"] = round((clock() - started) * 1000, 3)
        rows.append(row)

    complete = fetch is not None and all(row["status"] == "completed" for row in rows)
    aggregates = []
    if complete:
        for threshold in THRESHOLDS:
            for top_k in TOP_K_VALUES:
                relevant = [
                    {"retrieval_metrics": scenario["retrieval_metrics"]}
                    for row in rows for scenario in row["scenarios"]
                    if scenario["threshold"] == threshold and scenario["top_k"] == top_k
                ]
                aggregates.append({"threshold": threshold, "top_k": top_k,
                                   "metrics": aggregate_retrieval_metrics(relevant)})
    return {
        "schema_version": "1.0",
        "run_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if fetch is None else "live",
        "run_status": "dry_run" if fetch is None else "complete" if complete else "incomplete",
        "snapshot_fingerprint": snapshot["fingerprint"],
        "manifest_fingerprint": payload_fingerprint(manifest),
        "selection": {"selected_case_ids": [case["id"] for case in selected],
                      "excluded": excluded},
        "policy": {"query_processing": False, "generation": False,
                   "provider_calls_per_case": "one query embedding",
                   "candidates_per_case": 20,
                   "thresholds": list(THRESHOLDS), "top_k_values": list(TOP_K_VALUES)},
        "cases": rows,
        "scenario_aggregates": aggregates,
        "quality_scores_computed": False,
    }
