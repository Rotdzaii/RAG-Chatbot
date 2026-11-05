"""Manually check indexed URL sources; suitable for a future external scheduler.

Run from the repository root: python scripts/check_url_source_changes.py
This command fetches URLs but never reindexes documents or invokes models.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check indexed URL sources for changed bytes and notify admins."
    )
    parser.parse_args(argv)  # --help and invalid options exit before Settings/DB/network.

    backend = Path(__file__).resolve().parents[1] / "backend"
    sys.path.insert(0, str(backend))
    os.chdir(backend)  # Settings resolves backend/.env relative to the process cwd.

    from sqlalchemy import select
    from database import SessionLocal
    from rag.models import Document
    from rag.source_change_checks import check_url_source

    session = SessionLocal()
    try:
        source_ids = session.scalars(
            select(Document.id).where(Document.source_type == "url").order_by(Document.id)
        ).all()
        session.rollback()
        failures = 0
        for source_id in source_ids:
            result = check_url_source(session, source_id)
            print(f"{source_id} {result.status}")
            if result.status in {"fetch_error", "stale"}:
                failures += 1
        print(f"checked={len(source_ids)} failures={failures}")
        return 1 if failures else 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
