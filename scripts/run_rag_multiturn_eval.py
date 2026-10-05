"""Run or dry-run the P1 multi-turn RAG pipeline against an eval manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from rag_baseline import write_run_output
from rag_multiturn_eval import (
    build_dry_run_report,
    ensure_live_compatibility,
    run_live_multiturn_eval,
    select_eval_cases,
)
from rag_snapshot import read_snapshot
from validate_rag_eval_manifest import read_json, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_OUTPUT = ROOT / "data" / "rag_runs" / "multiturn_p1.json"


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _load_query_processing_config() -> dict[str, object]:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from rag.query_contract import query_processing_config

    return query_processing_config()


def _load_live_dependencies() -> tuple[
    Callable[[], dict[str, object]],
    object,
    object,
    object,
]:
    """Import database and provider-facing code only for an eligible live run."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from database import SessionLocal
    from export_rag_snapshot import export_from_database
    from rag.qa import answer_question
    from rag.query_contract import HistoryMessage

    return export_from_database, SessionLocal, answer_question, HistoryMessage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the P1 multi-turn RAG evaluation"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--case-id",
        help="Run one manifest case by its exact ID for focused diagnostics",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing run output"
    )
    parser.add_argument(
        "--case-interval-seconds",
        type=_non_negative_float,
        default=0.0,
        help="Wait between evaluated cases; default: 0",
    )
    args = parser.parse_args(argv)

    output_path = args.output.resolve()
    if output_path.exists() and not args.overwrite:
        print(
            f"ERROR: output already exists: {output_path}",
            file=sys.stderr,
        )
        return 1

    manifest = read_json(args.manifest)
    snapshot = read_snapshot(args.snapshot)
    errors = validate_manifest(manifest, snapshot)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if not isinstance(manifest, dict) or not isinstance(snapshot, dict):
        print("ERROR: manifest and snapshot must be JSON objects", file=sys.stderr)
        return 1

    try:
        selected, excluded = select_eval_cases(manifest, case_id=args.case_id)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"Cases: total={len(selected) + len(excluded)}, "
        f"selected={len(selected)}, excluded={len(excluded)}"
    )
    query_config = _load_query_processing_config()

    if args.dry_run:
        report = build_dry_run_report(
            manifest,
            snapshot,
            manifest_path=str(args.manifest),
            query_processing_config=query_config,
            case_id=args.case_id,
        )
        write_run_output(report, output_path, overwrite=args.overwrite)
        print(f"Dry-run output: {output_path}")
        return 0

    if not selected:
        print(
            "ERROR: no approved cases; live run stopped before database/provider access",
            file=sys.stderr,
        )
        return 2

    export_live_snapshot, session_factory, answer_question, history_message = (
        _load_live_dependencies()
    )
    live_snapshot = export_live_snapshot()
    live_verification = ensure_live_compatibility(snapshot, live_snapshot)

    with session_factory() as session:
        report = run_live_multiturn_eval(
            manifest,
            snapshot,
            manifest_path=str(args.manifest),
            query_processing_config=query_config,
            live_verification=live_verification,
            ask=lambda question, history: answer_question(
                session,
                question,
                history=[history_message(**message) for message in history],
            ),
            case_interval_seconds=args.case_interval_seconds,
            case_id=args.case_id,
        )
    write_run_output(report, output_path, overwrite=args.overwrite)
    print(f"Live output: {output_path}")
    execution = report["execution"]
    print(
        "Execution: "
        f"completed={execution['completed_cases']}, "
        f"errors={execution['error_cases']}, "
        "errors_by_stage="
        f"{json.dumps(execution['errors_by_stage'], ensure_ascii=False)}"
    )
    if report["run_status"] == "incomplete":
        print(
            "Retrieval metrics: incomplete run; partial executed-case metrics only: "
            f"{json.dumps(report['retrieval_metrics'], ensure_ascii=False)}"
        )
    else:
        print(
            "Retrieval metrics: "
            f"{json.dumps(report['retrieval_metrics'], ensure_ascii=False)}"
        )
    return 3 if int(execution["error_cases"]) > 0 else 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
