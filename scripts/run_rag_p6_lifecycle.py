"""Run a small P6 DB/embedding gate using a disposable TXT source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from rag_baseline import write_run_output
from rag_p6_lifecycle import (
    IndexedChunk, IndexedSource, SyntheticEmbeddingFailure, run_lifecycle_gate,
)


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_OUTPUT = ROOT / "data" / "rag_runs" / "p6_lifecycle_gate.json"


def _live_adapter():
    """Import all database/provider-facing code only for an explicit live run."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    from sqlalchemy import select
    from database import SessionLocal
    from rag.index_provenance import CHUNKING_PROFILE, current_embedding_profile
    from rag.ingestion import ingest_document
    from rag.models import Chunk, Document
    from rag.source_lifecycle import delete_source, replace_source

    class Adapter:
        def create(self, filename: str, content: bytes) -> UUID:
            with SessionLocal() as session:
                return ingest_document(session, filename, "text/plain", content).id

        def replace(self, source_id: UUID, filename: str, content: bytes,
                    *, fail_embedding: bool = False):
            with SessionLocal() as session:
                if fail_embedding:
                    with patch("rag.ingestion.embed_documents", side_effect=SyntheticEmbeddingFailure()):
                        return replace_source(session, source_id, source_type="file",
                                              filename=filename, mime_type="text/plain", content=content)
                return replace_source(session, source_id, source_type="file",
                                      filename=filename, mime_type="text/plain", content=content)

        def inspect(self, source_id: UUID) -> IndexedSource | None:
            with SessionLocal() as session:
                document = session.get(Document, source_id)
                if document is None:
                    return None
                rows = session.execute(
                    select(Chunk.id, Chunk.content, Chunk.embedding)
                    .where(Chunk.document_id == source_id).order_by(Chunk.chunk_index)
                ).all()
                return IndexedSource(
                    document.id, document.content_hash, document.embedding_profile,
                    document.chunking_profile,
                    tuple(IndexedChunk(row.id, row.content,
                                       len(row.embedding) if row.embedding is not None else None)
                          for row in rows),
                )

        def delete(self, source_id: UUID) -> bool:
            with SessionLocal() as session:
                return delete_source(session, source_id)

    return Adapter(), current_embedding_profile(), CHUNKING_PROFILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P6 disposable source lifecycle gate")
    parser.add_argument("--live", action="store_true", help="Write/delete a disposable DB source; uses two embedding batches")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() and not args.overwrite:
        print(f"ERROR: output already exists: {output}", file=sys.stderr)
        return 1

    if args.live:
        adapter, embedding_profile, chunking_profile = _live_adapter()
        report = run_lifecycle_gate(adapter, embedding_profile=embedding_profile,
                                    chunking_profile=chunking_profile)
    else:
        report = {
            "schema_version": "1.0", "phase": "P6", "mode": "dry_run",
            "status": "not_run", "expected_embedding_batches": 2,
            "planned_steps": ["create TXT", "skip unchanged", "replace changed",
                              "inject embedding failure", "delete TXT"],
            "database_access": False, "provider_access": False,
        }
    write_run_output(report, output, overwrite=args.overwrite)
    print(f"Lifecycle gate: {report['status']}; output: {output}")
    if report.get("document_id"):
        print(f"Disposable document ID: {report['document_id']}; cleanup={report['cleanup_status']}")
    return 0 if report["status"] in {"passed", "not_run"} else 3


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception as error:
        print(f"ERROR: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
