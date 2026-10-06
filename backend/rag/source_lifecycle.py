"""Admin-only source replacement and deletion within database transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from rag.index_provenance import CHUNKING_PROFILE, current_embedding_profile
from rag.ingestion import _build_chunk, _prepare_chunks
from rag.models import Chunk, Document


class SourceNotFound(Exception):
    pass


class SourceTypeMismatch(Exception):
    pass


class SourceChanged(Exception):
    """Another writer changed the source during embedding; retry from fresh data."""


@dataclass(frozen=True, slots=True)
class ReplacementResult:
    document_id: UUID
    filename: str
    chunk_count: int
    status: Literal["unchanged", "updated"]


def _chunk_count(session: Session, source_id: UUID) -> int:
    return int(session.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == source_id)) or 0)


def _is_current(document: Document, *, digest: str, mime_type: str, profile: str) -> bool:
    return (
        document.content_hash == digest
        and document.mime_type == mime_type
        and document.embedding_profile == profile
        and document.chunking_profile == CHUNKING_PROFILE
    )


def replace_source(
    session: Session,
    source_id: UUID,
    *,
    source_type: Literal["file", "url"],
    filename: str,
    mime_type: str,
    content: bytes,
    source_url: str | None = None,
) -> ReplacementResult:
    """Preserve document ID; atomically replace its chunks after preprocessing.

    A short initial transaction avoids embeddings when the stored bytes and
    indexing profiles already match. Embedding runs outside a row lock. A
    second locked read rejects concurrent changes rather than overwriting them.
    """
    if not filename.strip() or len(filename) > 255:
        raise ValueError("Invalid filename")
    digest = sha256(content).hexdigest()
    profile = current_embedding_profile()

    try:
        document = session.scalar(select(Document).where(Document.id == source_id).with_for_update())
        if document is None:
            raise SourceNotFound()
        if document.source_type != source_type or (
            source_type == "url" and document.source_url != source_url
        ):
            raise SourceTypeMismatch()
        initial_state = (
            document.content_hash,
            document.mime_type,
            document.embedding_profile,
            document.chunking_profile,
        )
        if _is_current(document, digest=digest, mime_type=mime_type, profile=profile):
            count = _chunk_count(session, source_id)
            if count:
                filename_changed = document.filename != filename
                if filename_changed:
                    document.filename = filename
                    document.updated_at = datetime.now(timezone.utc)
                if source_type == "url":
                    document.last_checked_at = datetime.now(timezone.utc)
                result = ReplacementResult(
                    document_id=source_id,
                    filename=filename,
                    chunk_count=count,
                    status="updated" if filename_changed else "unchanged",
                )
                session.commit()
                return result

        # Do not hold a database row lock while extraction or embedding runs.
        session.rollback()
        chunks, page_spans, embeddings = _prepare_chunks(
            content, mime_type, is_url=source_type == "url"
        )

        document = session.scalar(select(Document).where(Document.id == source_id).with_for_update())
        if document is None:
            raise SourceNotFound()
        if document.source_type != source_type or (
            source_type == "url" and document.source_url != source_url
        ):
            raise SourceTypeMismatch()
        if _is_current(document, digest=digest, mime_type=mime_type, profile=profile):
            # Another request finished the same update while we were embedding.
            count = _chunk_count(session, source_id)
            if count:
                if source_type == "url":
                    document.last_checked_at = datetime.now(timezone.utc)
                session.commit()
                return ReplacementResult(source_id, document.filename, count, "unchanged")
        if (
            document.content_hash,
            document.mime_type,
            document.embedding_profile,
            document.chunking_profile,
        ) != initial_state:
            raise SourceChanged()

        # The DELETE is executed before INSERTs in the *same* transaction so
        # the (document_id, chunk_index) uniqueness constraint cannot collide.
        session.execute(delete(Chunk).where(Chunk.document_id == source_id))
        new_chunks = [
            _build_chunk(index, chunk, embedding, page_spans)
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]
        for chunk in new_chunks:
            chunk.document_id = source_id
        session.add_all(new_chunks)
        document.filename = filename
        document.mime_type = mime_type
        document.content_hash = digest
        document.embedding_profile = profile
        document.chunking_profile = CHUNKING_PROFILE
        document.updated_at = datetime.now(timezone.utc)
        if source_type == "url":
            document.last_checked_at = datetime.now(timezone.utc)
        session.commit()
        return ReplacementResult(source_id, filename, len(new_chunks), "updated")
    except Exception:
        session.rollback()
        raise


def delete_source(session: Session, source_id: UUID) -> bool:
    """Delete a document and its chunks in one transaction."""
    try:
        document = session.scalar(select(Document).where(Document.id == source_id).with_for_update())
        if document is None:
            session.rollback()
            return False
        session.delete(document)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
