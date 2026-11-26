"""Verify and optionally copy existing source versions to Supabase Storage."""

import argparse
from collections import Counter
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError


def migrate_version(version, *, apply: bool) -> str:
    from rag.source_files import read_version, store_version

    reference = (version.id, version.mime_type, version.content_hash, version.byte_size)
    try:
        read_version(*reference, storage="supabase")
    except FileNotFoundError:
        content = read_version(*reference, storage="local")
    else:
        return "already_verified"

    if not apply:
        return "ready"
    try:
        store_version(version.id, version.mime_type, content, storage="supabase")
    except FileExistsError:
        # A concurrent copy may have created this key since we checked it.
        pass
    read_version(*reference, storage="supabase")
    return "copied_and_verified"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload verified local originals")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

    from database import SessionLocal
    from rag.models import SourceFileVersion
    from rag.supabase_source_storage import get_supabase_source_storage

    try:
        get_supabase_source_storage()
        with SessionLocal() as session:
            versions = session.scalars(select(SourceFileVersion).order_by(SourceFileVersion.id)).all()
    except SQLAlchemyError:
        print("Could not read source file versions from the configured database", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Could not access the configured bucket: {error}", file=sys.stderr)
        return 1

    results: Counter[str] = Counter()
    print("Mode: apply" if args.apply else "Mode: dry run")
    for version in versions:
        try:
            result = migrate_version(version, apply=args.apply)
        except (OSError, KeyError) as error:
            result = "blocked"
            print(f"{version.id}: {result}: {error}", file=sys.stderr)
        else:
            print(f"{version.id}: {result}")
        results[result] += 1
    print(
        f"Total: {len(versions)} | Already verified: {results['already_verified']} | "
        f"Ready: {results['ready']} | Copied and verified: {results['copied_and_verified']} | "
        f"Blocked: {results['blocked']}"
    )
    return int(results["blocked"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
