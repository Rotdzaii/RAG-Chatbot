"""Validate an exported RAG snapshot without database or provider access."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rag_snapshot import read_snapshot, snapshot_summary, validate_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a RAG snapshot offline")
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args(argv)

    snapshot = read_snapshot(args.snapshot)
    errors = validate_snapshot(snapshot)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Invalid snapshot: {len(errors)} error(s)", file=sys.stderr)
        return 1

    if not isinstance(snapshot, dict):
        print("ERROR: snapshot must be a JSON object", file=sys.stderr)
        return 1
    summary = snapshot_summary(snapshot)
    print(
        "Valid snapshot: "
        f"documents={summary['documents']}, chunks={summary['chunks']}, "
        f"sha256={summary['fingerprint']}"
    )
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
