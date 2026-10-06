"""Sweep retrieval settings using one embedding per approved direct question.

Run from backend with a manifest reviewed for the *current* corpus snapshot.
No answer generation, query rewriting, or writes to the database occur.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_baseline import ensure_live_snapshot_matches, write_run_output
from rag_retrieval_probe import build_report, select_direct_cases
from rag_snapshot import read_snapshot
from validate_rag_eval_manifest import read_json, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "rag_runs" / "retrieval_probe.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only retrieval threshold sweep")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    output = args.output.resolve()
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"output already exists: {output}")
    manifest = read_json(args.manifest)
    snapshot = read_snapshot(args.snapshot)
    errors = validate_manifest(manifest, snapshot)
    if errors:
        raise ValueError("Invalid manifest/snapshot: " + "; ".join(errors))
    selected, excluded = select_direct_cases(manifest, args.case_id)
    print(f"Direct retrieval: selected={len(selected)}, excluded={len(excluded)}")

    if args.dry_run:
        report = build_report(manifest, snapshot, case_id=args.case_id)
    else:
        if not selected:
            raise ValueError("No approved direct retrieval cases; provider not called")
        backend = str(ROOT / "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        from database import SessionLocal
        from export_rag_snapshot import export_from_database
        from rag.retrieval import retrieve_candidates

        # The snapshot captures metadata and embedding dimensions, not vector values.
        # An old manifest never silently inherits approval for a changed corpus.
        try:
            live_snapshot = export_from_database()
        except Exception as error:
            # Database drivers may include connection details in error messages.
            raise RuntimeError(f"Live snapshot check failed ({type(error).__name__})") from None
        ensure_live_snapshot_matches(snapshot, live_snapshot)
        try:
            with SessionLocal() as session:
                report = build_report(
                    manifest, snapshot, case_id=args.case_id,
                    fetch=lambda question: retrieve_candidates(session, question, top_k=20),
                )
        except Exception as error:
            raise RuntimeError(f"Retrieval session failed ({type(error).__name__})") from None

    write_run_output(report, output, overwrite=args.overwrite)
    print(f"Output: {output}")
    print(f"Run status: {report['run_status']}")
    if report["scenario_aggregates"]:
        baseline = next(item for item in report["scenario_aggregates"]
                        if item["threshold"] == 0.30 and item["top_k"] == 5)
        print("Current threshold/top_k: " + json.dumps(baseline, ensure_ascii=False))
    return 3 if report["run_status"] == "incomplete" else 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
