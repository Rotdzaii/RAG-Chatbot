"""Export a deterministic, read-only snapshot of RAG documents and chunks.

Run from ``backend`` so the existing ``backend/.env`` configuration is used:

    uv run --no-sync python ../scripts/export_rag_snapshot.py --output ../data/rag_snapshots/current.json
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import sys
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sqlalchemy import select

from rag_snapshot import build_snapshot, snapshot_summary, write_snapshot


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_OUTPUT = ROOT / "data" / "rag_snapshots" / "current.json"


def _isoformat(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def current_pipeline_config() -> dict[str, object]:
    """Describe code configuration separately from unavailable DB provenance."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    from rag.chunking import chunk_text
    from rag.embeddings import MODEL as embedding_model
    from rag.embeddings import OUTPUT_DIMENSIONALITY
    from rag.index_provenance import (
        BASELINE_EMBEDDING_PROFILE,
        CHUNKING_PROFILE,
        current_embedding_profile,
    )
    from rag.ingestion import MAX_URL_CHUNKS
    from rag.langchain_pipeline import MODEL as generation_model
    from rag.langchain_pipeline import SYSTEM_INSTRUCTION
    from rag.qa import answer_question
    from rag.query_contract import query_processing_config
    from rag.retrieval import MAX_COSINE_DISTANCE
    from rag.url_sources import ALLOWED_HOSTS, MAX_URL_BYTES

    chunk_signature = inspect.signature(chunk_text)
    answer_signature = inspect.signature(answer_question)
    return {
        "extraction": {
            "pdf_loader": "langchain_community.document_loaders.PyPDFLoader",
            "pdf_mode": "page",
            "extract_images": False,
            "txt_encoding": "utf-8-sig",
            "html_parser": "HTMLParser:skip-head-script-style-nav-footer-form-v1",
            "langchain_community_version": version("langchain-community"),
            "pypdf_version": version("pypdf"),
            "configured_from": "backend/rag/extraction.py",
        },
        "chunking": {
            "strategy": "fixed_character_window",
            "chunk_size": chunk_signature.parameters["chunk_size"].default,
            "overlap": chunk_signature.parameters["overlap"].default,
            "new_document_profile": CHUNKING_PROFILE,
            "configured_from": "backend/rag/chunking.py",
        },
        "url_source": {
            "scheme": "https",
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "max_bytes": MAX_URL_BYTES,
            "max_chunks": MAX_URL_CHUNKS,
            "follow_redirects": False,
        },
        "embedding": {
            "configured": {
                "provider": "gemini",
                "model": embedding_model,
                "output_dimension": OUTPUT_DIMENSIONALITY,
                "l2_normalized": True,
            },
            "persisted_provenance": {
                "model": "unknown",
                "version": "unknown",
                "reason": "snapshot schema 1.0 does not export per-document profiles; legacy rows are null",
            },
        },
        "query_processing": query_processing_config(),
        "retrieval": {
            "distance": "cosine",
            "max_cosine_distance": MAX_COSINE_DISTANCE,
            "default_top_k": answer_signature.parameters["top_k"].default,
            "compatible_embedding_profile": current_embedding_profile(),
            "legacy_null_profile_allowed": (
                current_embedding_profile() == BASELINE_EMBEDDING_PROFILE
            ),
            "configured_from": "backend/rag/retrieval.py and backend/rag/qa.py",
        },
        "generation": {
            "configured": {
                "provider": "gemini",
                "model": generation_model,
                "temperature": "unknown",
                "system_instruction_sha256": hashlib.sha256(
                    SYSTEM_INSTRUCTION.encode("utf-8")
                ).hexdigest(),
            },
            "persisted_provenance": {
                "model": "unknown",
                "version": "unknown",
                "reason": "generation model/version is not stored with documents or chunks",
            },
        },
    }


def export_from_database(*, exported_at: str | None = None) -> dict[str, object]:
    """Run exactly two SELECTs in one session transaction and build a snapshot."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    from database import SessionLocal
    from rag.models import Chunk, Document

    document_statement = select(
        Document.id,
        Document.filename,
        Document.mime_type,
        Document.source_type,
        Document.source_url,
        Document.category,
        Document.audience,
        Document.content_hash,
        Document.published_at,
        Document.last_checked_at,
        Document.effective_from,
        Document.effective_to,
        Document.created_at,
        Document.updated_at,
    ).order_by(Document.id)
    chunk_statement = select(
        Chunk.id,
        Chunk.document_id,
        Chunk.chunk_index,
        Chunk.content,
        Chunk.embedding,
        Chunk.created_at,
    ).order_by(Chunk.document_id, Chunk.chunk_index, Chunk.id)

    with SessionLocal() as session, session.begin():
        document_rows = session.execute(document_statement).mappings().all()
        chunk_rows = session.execute(chunk_statement).mappings().all()

    documents = [
        {
            "id": str(row["id"]),
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "category": row["category"],
            "audience": row["audience"],
            "content_hash": row["content_hash"],
            "published_at": _isoformat(row["published_at"]),
            "last_checked_at": _isoformat(row["last_checked_at"]),
            "effective_from": _isoformat(row["effective_from"]),
            "effective_to": _isoformat(row["effective_to"]),
            "created_at": _isoformat(row["created_at"]),
            "updated_at": _isoformat(row["updated_at"]),
        }
        for row in document_rows
    ]
    chunks = []
    for row in chunk_rows:
        embedding = row["embedding"]
        chunks.append(
            {
                "id": str(row["id"]),
                "document_id": str(row["document_id"]),
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "embedding_present": embedding is not None,
                "embedding_dimension": len(embedding) if embedding is not None else None,
                "created_at": _isoformat(row["created_at"]),
            }
        )

    timestamp = exported_at or datetime.now(timezone.utc).isoformat()
    return build_snapshot(
        documents=documents,
        chunks=chunks,
        pipeline_config=current_pipeline_config(),
        exported_at=timestamp,
    )


def _format_dimensions(dimensions: Any) -> str:
    if not isinstance(dimensions, dict) or not dimensions:
        return "none"
    return ", ".join(f"{dimension}:{count}" for dimension, count in dimensions.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a deterministic read-only RAG corpus snapshot"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing snapshot"
    )
    args = parser.parse_args(argv)

    snapshot = export_from_database()
    write_snapshot(snapshot, args.output.resolve(), overwrite=args.overwrite)
    summary = snapshot_summary(snapshot)
    print(f"Snapshot: {args.output.resolve()}")
    print(f"Documents: {summary['documents']}")
    print(f"Chunks: {summary['chunks']}")
    print(f"Embedding dimensions: {_format_dimensions(summary['embedding_dimensions'])}")
    print(f"Missing embeddings: {summary['missing_embeddings']}")
    print(f"SHA-256: {summary['fingerprint']}")
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
