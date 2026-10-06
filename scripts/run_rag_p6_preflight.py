"""Validate a candidate P6 snapshot and all intended eval manifests offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_baseline import write_run_output
from rag_p6_preflight import build_preflight_report
from rag_snapshot import read_snapshot
from validate_rag_eval_manifest import read_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "rag_runs" / "p6_preflight.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P6 offline corpus/eval readiness gate")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    output = args.output.resolve()
    if output.exists() and not args.overwrite:
        print(f"ERROR: output already exists: {output}", file=sys.stderr)
        return 1
    snapshot = read_snapshot(args.snapshot)
    manifests = [(str(path), read_json(path)) for path in args.manifest]
    report = build_preflight_report(snapshot, manifests)
    write_run_output(report, output, overwrite=args.overwrite)
    print(f"Preflight: {report['status']}; output: {output}")
    for item in report["manifests"]:
        print(f"  {item['manifest']}: {item['status']}, errors={len(item['errors'])}")
    return 0 if report["status"] == "ready_for_live_compatibility_check" else 2


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
