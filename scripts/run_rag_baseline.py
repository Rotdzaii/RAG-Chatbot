"""Run or dry-run the current single-turn RAG pipeline against an eval manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from rag_baseline import (
    build_dry_run_report,
    ensure_live_snapshot_matches,
    run_live_baseline,
    select_cases,
    write_run_output,
)
from rag_snapshot import read_snapshot
from validate_rag_eval_manifest import read_json, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_OUTPUT = ROOT / "data" / "rag_runs" / "baseline.json"


def _load_live_dependencies() -> tuple[Callable[[], dict[str, object]], object, object]:
    """Import DB/provider-facing code only after approved-case filtering."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from database import SessionLocal
    from export_rag_snapshot import export_from_database
    from rag.qa import answer_question

    return export_from_database, SessionLocal, answer_question


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the unchanged P0 single-turn RAG baseline"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing run output"
    )
    args = parser.parse_args(argv)

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

    selected, excluded = select_cases(manifest)
    print(
        f"Cases: total={len(selected) + len(excluded)}, "
        f"selected={len(selected)}, excluded={len(excluded)}"
    )

    if args.dry_run:
        report = build_dry_run_report(
            manifest,
            snapshot,
            manifest_path=str(args.manifest),
        )
        write_run_output(report, args.output.resolve(), overwrite=args.overwrite)
        print(f"Dry-run output: {args.output.resolve()}")
        return 0

    if not selected:
        print(
            "ERROR: no approved cases; live run stopped before database/provider access",
            file=sys.stderr,
        )
        return 2

    export_live_snapshot, session_factory, answer_question = _load_live_dependencies()
    live_snapshot = export_live_snapshot()
    ensure_live_snapshot_matches(snapshot, live_snapshot)

    with session_factory() as session:
        report = run_live_baseline(
            manifest,
            snapshot,
            manifest_path=str(args.manifest),
            ask=lambda question: answer_question(session, question),
        )
    write_run_output(report, args.output.resolve(), overwrite=args.overwrite)
    metrics = report["retrieval_metrics"]
    print(f"Live output: {args.output.resolve()}")
    print(f"Retrieval metrics: {json.dumps(metrics, ensure_ascii=False)}")
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
