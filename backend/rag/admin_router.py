from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from langchain_google_genai._common import GoogleGenerativeAIError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth import require_admin
from database import SessionLocal
from rag.ingestion import ingest_document
from rag.knowledge_sources import get_knowledge_source, list_knowledge_sources
from rag.models import Document
from rag.source_lifecycle import (
    SourceChanged,
    SourceNotFound,
    SourceTypeMismatch,
    delete_source,
    replace_source,
)
from rag.url_sources import (
    SourceFetchError,
    SourceTooLarge,
    SourceURLValidationError,
    UnsupportedSourceType,
    fetch_source,
    normalize_source_url,
)


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


class URLSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)


class SourceMutationResponse(BaseModel):
    document_id: UUID
    filename: str
    chunk_count: int
    status: Literal["updated", "unchanged"]


MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_FILE_MIME_TYPES = {"application/pdf", "text/plain"}


def _replacement_response(result: object) -> SourceMutationResponse:
    return SourceMutationResponse.model_validate(result, from_attributes=True)


def _mutation_error(error: Exception) -> HTTPException:
    if isinstance(error, SourceNotFound):
        return HTTPException(status_code=404, detail="Knowledge source not found")
    if isinstance(error, SourceTypeMismatch):
        return HTTPException(status_code=409, detail="Source type or URL has changed")
    if isinstance(error, SourceChanged):
        return HTTPException(status_code=409, detail="Source changed during re-index; retry")
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    return HTTPException(status_code=503, detail="Source update is unavailable")


@router.post("/knowledge-sources/url", status_code=status.HTTP_201_CREATED)
def upload_url_source(request: URLSourceRequest) -> dict[str, str | int]:
    try:
        normalized = normalize_source_url(request.url)
    except SourceURLValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # Avoid spending embedding quota on a URL already in the database. The
    # unique source_url constraint still handles concurrent uploads.
    session = SessionLocal()
    try:
        existing = session.scalar(
            select(Document.id).where(Document.source_url == normalized)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="Source URL already exists")
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    finally:
        session.close()

    try:
        fetched = fetch_source(normalized)
    except UnsupportedSourceType as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except SourceTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except SourceFetchError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    session = SessionLocal()
    try:
        document = ingest_document(
            session,
            fetched.filename,
            fetched.mime_type,
            fetched.content,
            source_url=fetched.url,
        )
        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "chunk_count": len(document.chunks),
        }
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="Source URL already exists") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    except (GoogleGenerativeAIError, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Ingestion is unavailable") from error
    finally:
        session.close()


@router.post("/knowledge-sources/{source_id}/refresh", response_model=SourceMutationResponse)
def refresh_url_source(source_id: UUID) -> SourceMutationResponse:
    # Check existence/type before fetching. replace_source checks again under
    # a row lock to handle concurrent deletion or changes.
    session = SessionLocal()
    try:
        source = session.scalar(select(Document).where(Document.id == source_id))
        if source is None:
            raise HTTPException(status_code=404, detail="Knowledge source not found")
        if source.source_type != "url" or not source.source_url:
            raise HTTPException(status_code=409, detail="Source is not a URL")
        url = source.source_url
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    finally:
        session.close()

    try:
        fetched = fetch_source(url)
    except SourceURLValidationError as error:
        raise HTTPException(status_code=409, detail="Stored source URL is invalid") from error
    except UnsupportedSourceType as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except SourceTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except SourceFetchError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    session = SessionLocal()
    try:
        result = replace_source(
            session, source_id, source_type="url", filename=fetched.filename,
            mime_type=fetched.mime_type, content=fetched.content,
            source_url=fetched.url,
        )
        return _replacement_response(result)
    except (SourceNotFound, SourceTypeMismatch, SourceChanged, ValueError,
            SQLAlchemyError, GoogleGenerativeAIError, RuntimeError) as error:
        raise _mutation_error(error) from error
    finally:
        session.close()


@router.put("/knowledge-sources/{source_id}/file", response_model=SourceMutationResponse)
def replace_file_source(
    source_id: UUID,
    file: UploadFile | None = File(default=None),
) -> SourceMutationResponse:
    if file is None or not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    if file.content_type not in ALLOWED_FILE_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported MIME type")
    content = file.file.read(MAX_FILE_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="File must not be empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MiB")

    session = SessionLocal()
    try:
        result = replace_source(
            session, source_id, source_type="file", filename=file.filename,
            mime_type=file.content_type, content=content,
        )
        return _replacement_response(result)
    except (SourceNotFound, SourceTypeMismatch, SourceChanged, ValueError,
            SQLAlchemyError, GoogleGenerativeAIError, RuntimeError) as error:
        raise _mutation_error(error) from error
    finally:
        session.close()


@router.delete("/knowledge-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_source(source_id: UUID) -> None:
    session = SessionLocal()
    try:
        if not delete_source(session, source_id):
            raise HTTPException(status_code=404, detail="Knowledge source not found")
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    finally:
        session.close()


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
