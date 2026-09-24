from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from auth import require_admin
from database import SessionLocal
from rag.knowledge_sources import get_knowledge_source, list_knowledge_sources


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class KnowledgeSourceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class KnowledgeSourceResponse(BaseModel):
    items: list[KnowledgeSourceItem]
    total: int
    limit: int
    offset: int


@router.get("/knowledge-sources", response_model=KnowledgeSourceResponse)
def get_knowledge_sources(
    source_type: Literal["file", "url"] | None = Query(default=None),
    category: str | None = Query(default=None),
    audience: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> KnowledgeSourceResponse:
    session = SessionLocal()
    try:
        page = list_knowledge_sources(
            session,
            source_type=source_type,
            category=category,
            audience=audience,
            limit=limit,
            offset=offset,
        )
        return KnowledgeSourceResponse(
            items=[KnowledgeSourceItem.model_validate(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503, detail="Knowledge sources are unavailable"
        ) from error
    finally:
        session.close()


@router.get("/knowledge-sources/{source_id}", response_model=KnowledgeSourceItem)
def get_knowledge_source_detail(source_id: UUID) -> KnowledgeSourceItem:
    session = SessionLocal()
    try:
        source = get_knowledge_source(session, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Knowledge source not found")
        return KnowledgeSourceItem.model_validate(source)
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503, detail="Knowledge sources are unavailable"
        ) from error
    finally:
        session.close()
