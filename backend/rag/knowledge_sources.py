from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag.models import Chunk, Document


@dataclass(frozen=True, slots=True)
class KnowledgeSourceRecord:
    id: UUID
    filename: str
    mime_type: str
    source_type: str
    source_url: str | None
    category: str | None
    audience: str | None
    content_hash: str | None
    published_at: datetime | None
    last_checked_at: datetime | None
    effective_from: date | None
    effective_to: date | None
    created_at: datetime
    updated_at: datetime
    chunk_count: int


@dataclass(frozen=True, slots=True)
class KnowledgeSourcePage:
    items: list[KnowledgeSourceRecord]
    total: int
    limit: int
    offset: int


def _knowledge_source_statement():
    chunk_counts = (
        select(
            Chunk.document_id.label("document_id"),
            func.count(Chunk.id).label("chunk_count"),
        )
        .group_by(Chunk.document_id)
        .subquery()
    )
    return select(
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
        func.coalesce(chunk_counts.c.chunk_count, 0).label("chunk_count"),
    ).outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)


def _map_knowledge_source(row: Mapping[str, Any]) -> KnowledgeSourceRecord:
    return KnowledgeSourceRecord(
        id=row["id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        category=row["category"],
        audience=row["audience"],
        content_hash=row["content_hash"],
        published_at=row["published_at"],
        last_checked_at=row["last_checked_at"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        chunk_count=int(row["chunk_count"]),
    )


def list_knowledge_sources(
    session: Session,
    *,
    source_type: str | None = None,
    category: str | None = None,
    audience: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> KnowledgeSourcePage:
    filters = []
    if source_type is not None:
        filters.append(Document.source_type == source_type)
    if category is not None:
        filters.append(Document.category == category)
    if audience is not None:
        filters.append(Document.audience == audience)

    total_statement = select(func.count()).select_from(Document).where(*filters)
    total = int(session.scalar(total_statement) or 0)

    statement = (
        _knowledge_source_statement()
        .where(*filters)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = session.execute(statement).mappings()
    items = [_map_knowledge_source(row) for row in rows]
    return KnowledgeSourcePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


def get_knowledge_source(
    session: Session, source_id: UUID
) -> KnowledgeSourceRecord | None:
    statement = _knowledge_source_statement().where(Document.id == source_id)
    row = session.execute(statement).mappings().one_or_none()
    if row is None:
        return None
    return _map_knowledge_source(row)
