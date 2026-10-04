"""Validate P0 evaluation cases against an exported RAG snapshot offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from rag_snapshot import read_snapshot, validate_snapshot


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA_VERSION = "1.0"
QUERY_TYPES = {
    "standalone",
    "paraphrase",
    "typo",
    "follow_up",
    "ambiguous",
    "out_of_scope",
}
ANSWERABILITY_VALUES = {
    "unknown",
    "answerable",
    "partially_answerable",
    "unanswerable",
}
REVIEW_STATUS_VALUES = {"pending_review", "approved", "rejected"}
METRIC_VALUES = {"not_applicable", "pending_review", "applicable"}
EVIDENCE_KINDS = {"supporting", "context_only"}

MANIFEST_KEYS = {
    "schema_version",
    "phase",
    "name",
    "snapshot",
    "review_policy",
    "corpus_notes",
    "cases",
}
CASE_KEYS = {
    "id",
    "query_type",
    "answerability",
    "review_status",
    "reviewer",
    "reviewed_at",
    "question",
    "history",
    "evidence",
    "expected_behavior",
    "required_facts",
    "forbidden_claims",
    "fail_if",
    "metric_applicability",
}
OPTIONAL_CASE_KEYS = {"metadata", "review_rationale", "required_behaviors"}


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def validate_manifest(manifest: object, snapshot: object) -> list[str]:
    """Validate structure, review state, fingerprint, and exact evidence spans."""
    errors: list[str] = []
    snapshot_errors = validate_snapshot(snapshot)
    errors.extend(f"snapshot: {error}" for error in snapshot_errors)
    if not isinstance(manifest, dict):
        return errors + ["manifest must be a JSON object"]
    if not isinstance(snapshot, dict):
        return errors

    _check_keys(manifest, MANIFEST_KEYS, "manifest", errors)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append(f"schema_version must be {MANIFEST_SCHEMA_VERSION!r}")
    if manifest.get("phase") != "P0.2":
        errors.append("phase must be 'P0.2'")
    _require_text(manifest.get("name"), "name", errors)

    snapshot_ref = manifest.get("snapshot")
    if not isinstance(snapshot_ref, dict):
        errors.append("snapshot must be an object")
    else:
        _check_keys(
            snapshot_ref,
            {"path", "fingerprint_algorithm", "fingerprint"},
            "snapshot",
            errors,
        )
        _require_text(snapshot_ref.get("path"), "snapshot.path", errors)
        if snapshot_ref.get("fingerprint_algorithm") != "sha256":
            errors.append("snapshot.fingerprint_algorithm must be 'sha256'")
        manifest_fingerprint = snapshot_ref.get("fingerprint")
        actual_fingerprint = snapshot.get("fingerprint")
        if manifest_fingerprint != actual_fingerprint:
            errors.append(
                "snapshot fingerprint mismatch: "
                f"manifest={manifest_fingerprint!r}, snapshot={actual_fingerprint!r}"
            )

    review_policy = manifest.get("review_policy")
    if not isinstance(review_policy, dict):
        errors.append("review_policy must be an object")
    else:
        _check_keys(
            review_policy,
            {
                "score_only_review_status",
                "pending_answerability",
                "history_is_fixture_not_gold",
                "required_facts_are_draft_until_approved",
            },
            "review_policy",
            errors,
        )
        if review_policy.get("score_only_review_status") != "approved":
            errors.append("review_policy.score_only_review_status must be 'approved'")
        if review_policy.get("pending_answerability") != "unknown":
            errors.append("review_policy.pending_answerability must be 'unknown'")
        for field in (
            "history_is_fixture_not_gold",
            "required_facts_are_draft_until_approved",
        ):
            if review_policy.get(field) is not True:
                errors.append(f"review_policy.{field} must be true")

    documents, chunks = _snapshot_indexes(snapshot, errors)
    corpus_notes = manifest.get("corpus_notes")
    if not isinstance(corpus_notes, list):
        errors.append("corpus_notes must be an array")
    else:
        note_ids: set[str] = set()
        for index, note in enumerate(corpus_notes):
            prefix = f"corpus_notes[{index}]"
            if not isinstance(note, dict):
                errors.append(f"{prefix} must be an object")
                continue
            _check_keys(note, {"id", "note", "evidence"}, prefix, errors)
            note_id = _require_text(note.get("id"), f"{prefix}.id", errors)
            if note_id is not None:
                if note_id in note_ids:
                    errors.append(f"duplicate corpus note id: {note_id}")
                note_ids.add(note_id)
            _require_text(note.get("note"), f"{prefix}.note", errors)
            _validate_evidence(
                note.get("evidence"), prefix, documents, chunks, errors
            )

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be an array")
        return errors
    if not cases:
        errors.append("cases must not be empty")

    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _check_keys_with_optional(
            case, CASE_KEYS, OPTIONAL_CASE_KEYS, prefix, errors
        )

        case_id = _require_text(case.get("id"), f"{prefix}.id", errors)
        if case_id is not None:
            if case_id in case_ids:
                errors.append(f"duplicate case id: {case_id}")
            case_ids.add(case_id)

        query_type = case.get("query_type")
        if query_type not in QUERY_TYPES:
            errors.append(f"{prefix}.query_type is invalid")
        answerability = case.get("answerability")
        if answerability not in ANSWERABILITY_VALUES:
            errors.append(f"{prefix}.answerability is invalid")
        review_status = case.get("review_status")
        if review_status not in REVIEW_STATUS_VALUES:
            errors.append(f"{prefix}.review_status is invalid")
        _validate_review_state(case, prefix, errors)

        _require_text(case.get("question"), f"{prefix}.question", errors)
        _require_text(
            case.get("expected_behavior"), f"{prefix}.expected_behavior", errors
        )
        _validate_history(case.get("history"), prefix, errors)
        supporting_count = _validate_evidence(
            case.get("evidence"), prefix, documents, chunks, errors
        )
        _validate_text_list(
            case.get("required_facts"),
            f"{prefix}.required_facts",
            errors,
            allow_empty=True,
        )
        for field in ("forbidden_claims", "fail_if"):
            _validate_text_list(case.get(field), f"{prefix}.{field}", errors)
        _validate_optional_rubric(case, prefix, errors)

        metrics = case.get("metric_applicability")
        if not isinstance(metrics, dict):
            errors.append(f"{prefix}.metric_applicability must be an object")
        else:
            _check_keys(
                metrics,
                {"retrieval", "answer_quality", "query_rewriting"},
                f"{prefix}.metric_applicability",
                errors,
            )
            for field in ("retrieval", "answer_quality", "query_rewriting"):
                if metrics.get(field) not in METRIC_VALUES:
                    errors.append(
                        f"{prefix}.metric_applicability.{field} is invalid"
                    )
            if metrics.get("query_rewriting") != "not_applicable":
                errors.append(
                    f"{prefix}.metric_applicability.query_rewriting must be "
                    "'not_applicable' in P0.2"
                )
            retrieval = metrics.get("retrieval")
            if supporting_count == 0 and retrieval != "not_applicable":
                errors.append(
                    f"{prefix}.metric_applicability.retrieval must be "
                    "'not_applicable' without supporting evidence"
                )
            if supporting_count > 0 and retrieval == "not_applicable":
                errors.append(
                    f"{prefix}.metric_applicability.retrieval cannot be "
                    "'not_applicable' with supporting evidence"
                )

    return errors


def manifest_summary(manifest: object) -> dict[str, int]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        raise ValueError("manifest cases are missing")
    cases = manifest["cases"]
    counts = Counter(
        case.get("review_status")
        for case in cases
        if isinstance(case, dict)
    )
    return {
        "total": len(cases),
        "approved": counts["approved"],
        "pending_review": counts["pending_review"],
        "rejected": counts["rejected"],
        "scored": counts["approved"],
        "excluded": len(cases) - counts["approved"],
    }


def _snapshot_indexes(
    snapshot: dict[str, object], errors: list[str]
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        return {}, {}
    raw_documents = payload.get("documents")
    raw_chunks = payload.get("chunks")
    documents = {
        item["id"]: item
        for item in raw_documents or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    chunks = {
        item["id"]: item
        for item in raw_chunks or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not documents or not chunks:
        errors.append("snapshot must contain documents and chunks for evidence checks")
    return documents, chunks


def _validate_evidence(
    value: object,
    parent_prefix: str,
    documents: dict[str, dict[str, object]],
    chunks: dict[str, dict[str, object]],
    errors: list[str],
) -> int:
    if not isinstance(value, list):
        errors.append(f"{parent_prefix}.evidence must be an array")
        return 0
    supporting_count = 0
    for index, evidence in enumerate(value):
        prefix = f"{parent_prefix}.evidence[{index}]"
        if not isinstance(evidence, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _check_keys(
            evidence, {"kind", "document_id", "chunk_id", "quote"}, prefix, errors
        )
        kind = evidence.get("kind")
        if kind not in EVIDENCE_KINDS:
            errors.append(f"{prefix}.kind is invalid")
        elif kind == "supporting":
            supporting_count += 1
        document_id = _require_text(
            evidence.get("document_id"), f"{prefix}.document_id", errors
        )
        chunk_id = _require_text(
            evidence.get("chunk_id"), f"{prefix}.chunk_id", errors
        )
        quote = _require_text(evidence.get("quote"), f"{prefix}.quote", errors)

        if document_id is not None and document_id not in documents:
            errors.append(f"{prefix}.document_id does not exist in snapshot")
        chunk = chunks.get(chunk_id) if chunk_id is not None else None
        if chunk_id is not None and chunk is None:
            errors.append(f"{prefix}.chunk_id does not exist in snapshot")
        if chunk is not None and document_id is not None:
            if chunk.get("document_id") != document_id:
                errors.append(
                    f"{prefix} points to chunk {chunk_id} outside document {document_id}"
                )
            content = chunk.get("content")
            if quote is not None and (
                not isinstance(content, str) or quote not in content
            ):
                errors.append(f"{prefix}.quote is not present in the referenced chunk")
    return supporting_count


def _validate_review_state(
    case: dict[str, object], prefix: str, errors: list[str]
) -> None:
    status = case.get("review_status")
    answerability = case.get("answerability")
    reviewer = case.get("reviewer")
    reviewed_at = case.get("reviewed_at")
    if status == "pending_review":
        if answerability != "unknown":
            errors.append(f"{prefix}.answerability must be 'unknown' while pending")
        if reviewer is not None or reviewed_at is not None:
            errors.append(f"{prefix} pending review must not have reviewer/reviewed_at")
    elif status == "approved":
        if answerability == "unknown":
            errors.append(f"{prefix}.answerability must be reviewed before approval")
        _require_text(reviewer, f"{prefix}.reviewer", errors)
        _require_text(reviewed_at, f"{prefix}.reviewed_at", errors)
    elif status == "rejected":
        _require_text(reviewer, f"{prefix}.reviewer", errors)
        _require_text(reviewed_at, f"{prefix}.reviewed_at", errors)


def _validate_history(value: object, prefix: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{prefix}.history must be an array")
        return
    for index, message in enumerate(value):
        message_prefix = f"{prefix}.history[{index}]"
        if not isinstance(message, dict):
            errors.append(f"{message_prefix} must be an object")
            continue
        _check_keys(message, {"role", "content"}, message_prefix, errors)
        if message.get("role") not in {"user", "assistant"}:
            errors.append(f"{message_prefix}.role is invalid")
        _require_text(message.get("content"), f"{message_prefix}.content", errors)


def _validate_text_list(
    value: object,
    prefix: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a non-empty array"
        errors.append(f"{prefix} must be {qualifier}")
        return
    for index, item in enumerate(value):
        _require_text(item, f"{prefix}[{index}]", errors)


def _require_text(value: Any, prefix: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix} must be a non-empty string")
        return None
    return value


def _check_keys(
    value: dict[str, object],
    expected: set[str],
    prefix: str,
    errors: list[str],
) -> None:
    for key in sorted(expected - value.keys()):
        errors.append(f"{prefix}.{key} is required")
    for key in sorted(value.keys() - expected):
        errors.append(f"{prefix}.{key} is not allowed")


def _check_keys_with_optional(
    value: dict[str, object],
    required: set[str],
    optional: set[str],
    prefix: str,
    errors: list[str],
) -> None:
    for key in sorted(required - value.keys()):
        errors.append(f"{prefix}.{key} is required")
    for key in sorted(value.keys() - required - optional):
        errors.append(f"{prefix}.{key} is not allowed")


def _validate_optional_rubric(
    case: dict[str, object], prefix: str, errors: list[str]
) -> None:
    if "review_rationale" in case:
        _require_text(case.get("review_rationale"), f"{prefix}.review_rationale", errors)

    has_metadata = "metadata" in case
    has_required_behaviors = "required_behaviors" in case
    if has_metadata != has_required_behaviors:
        errors.append(
            f"{prefix}.metadata and {prefix}.required_behaviors "
            "must be provided together when extended rubric is used"
        )
    if not has_metadata:
        return

    _validate_text_list(
        case.get("required_behaviors"), f"{prefix}.required_behaviors", errors
    )

    metadata = case.get("metadata")
    if not isinstance(metadata, dict):
        errors.append(f"{prefix}.metadata must be an object")
        return
    _check_keys(
        metadata,
        {"history_fixture", "history_is_gold"},
        f"{prefix}.metadata",
        errors,
    )
    history_fixture = metadata.get("history_fixture")
    history_is_gold = metadata.get("history_is_gold")
    if not isinstance(history_fixture, bool):
        errors.append(f"{prefix}.metadata.history_fixture must be a boolean")
    if history_is_gold is not False:
        errors.append(f"{prefix}.metadata.history_is_gold must be false")
    history = case.get("history")
    if history_fixture is True and (not isinstance(history, list) or not history):
        errors.append(f"{prefix}.history must be non-empty for a history fixture")
    if history_fixture is False and isinstance(history, list) and history:
        errors.append(f"{prefix}.metadata.history_fixture must be true when history exists")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a P0 evaluation manifest against a RAG snapshot"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Override the snapshot path declared in the manifest",
    )
    args = parser.parse_args(argv)

    manifest = read_json(args.manifest)
    if not isinstance(manifest, dict):
        print("ERROR: manifest must be a JSON object", file=sys.stderr)
        return 1
    snapshot_path = args.snapshot
    if snapshot_path is None:
        snapshot_ref = manifest.get("snapshot")
        declared_path = snapshot_ref.get("path") if isinstance(snapshot_ref, dict) else None
        if not isinstance(declared_path, str) or not declared_path:
            print("ERROR: manifest snapshot.path is missing", file=sys.stderr)
            return 1
        snapshot_path = ROOT / declared_path

    snapshot = read_snapshot(snapshot_path)
    errors = validate_manifest(manifest, snapshot)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Invalid manifest: {len(errors)} error(s)", file=sys.stderr)
        return 1

    summary = manifest_summary(manifest)
    print(
        "Valid manifest: "
        f"total={summary['total']}, approved={summary['approved']}, "
        f"pending_review={summary['pending_review']}, "
        f"rejected={summary['rejected']}"
    )
    print(
        f"Scoring: included={summary['scored']}, excluded={summary['excluded']}"
    )
    print("Quality scores: not computed")
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
