"""Carry verified evidence to a new snapshot without carrying approvals."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from rag_snapshot import read_snapshot, validate_snapshot
from validate_rag_eval_manifest import read_json, validate_manifest


def prepare_review_manifest(
    source: object, snapshot: object, *, snapshot_ref: str,
) -> dict[str, object]:
    if not snapshot_ref.strip():
        raise ValueError("Snapshot reference is required")
    snapshot_errors = validate_snapshot(snapshot)
    if snapshot_errors:
        raise ValueError("Snapshot is invalid: " + "; ".join(snapshot_errors))

    # The sole permitted difference is the snapshot fingerprint. The validator
    # also checks that every document/chunk ID and exact evidence quote remains.
    errors = validate_manifest(source, snapshot)
    mismatches = [error for error in errors if error.startswith("snapshot fingerprint mismatch:")]
    if errors != mismatches or len(mismatches) > 1:
        raise ValueError("Evidence or manifest is invalid: " + "; ".join(errors))
    if not isinstance(source, dict) or not isinstance(snapshot, dict):
        raise ValueError("Manifest and snapshot must be objects")

    prepared = copy.deepcopy(source)
    prepared["name"] = str(source["name"]) + " — P6 pending review"
    prepared["snapshot"]["path"] = snapshot_ref
    prepared["snapshot"]["fingerprint"] = snapshot["fingerprint"]
    for case in prepared["cases"]:
        case["answerability"] = "unknown"
        case["review_status"] = "pending_review"
        case["reviewer"] = None
        case["reviewed_at"] = None
        case["review_rationale"] = (
            "Evidence IDs and quotes matched this snapshot offline. "
            "Prior approval does not transfer; a reviewer must check content, "
            "answerability and rubric before scoring."
        )
        metrics = case["metric_applicability"]
        metrics["retrieval"] = (
            "pending_review" if any(
                evidence["kind"] == "supporting" for evidence in case["evidence"]
            ) else "not_applicable"
        )
        metrics["answer_quality"] = "pending_review"
        metrics["query_rewriting"] = "not_applicable"

    prepared_errors = validate_manifest(prepared, snapshot)
    if prepared_errors:
        raise ValueError("Prepared manifest is invalid: " + "; ".join(prepared_errors))
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a pending-review eval manifest for a new snapshot (offline)"
    )
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-ref", required=True,
                        help="Repository-relative snapshot path recorded in the manifest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        print(f"ERROR: output already exists: {output}", file=sys.stderr)
        return 1
    prepared = prepare_review_manifest(
        read_json(args.source_manifest), read_snapshot(args.snapshot),
        snapshot_ref=args.snapshot_ref,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(prepared, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Review draft: {output}; cases={len(prepared['cases'])}; approved=0")
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
