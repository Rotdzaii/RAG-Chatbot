from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Event
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from google.genai.errors import APIError
from langchain_google_genai._common import GoogleGenerativeAIError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

from auth import AuthenticatedUser, get_authenticated_user, require_admin
from database import SessionLocal
from rag.conversations import (
    create_title_from_question,
    expire_grounded_text,
    expire_legacy_grounding,
    get_owned_conversation,
    list_recent_owned_messages,
    update_owned_conversation,
)
from rag.external_answers import GroundedResult
from rag.ingestion import ingest_document
from rag.ocr import OCRFailed, OCRUnavailable
from rag.models import Conversation, Message
from rag.qa import answer_question
from rag.provider_errors import ProviderCallError
from rag.query_processing import QueryProcessingError
from rag.question_outcomes import QuestionExecution, current_execution
from rag.question_tracking import (
    PriorResponseDeleted, RequestFingerprintConflict, begin_turn, complete_turn, finish_rolled_back_turn,
)
from rag.source_metadata import MetadataValue, RetrievalFilters
from rag.progress import (
    ProgressContext, QuestionCancelled, check_connected, current, message_id, notify, request_guard,
)


router = APIRouter()
ALLOWED_MIME_TYPES = {"application/pdf", "text/plain"}
MAX_FILE_SIZE = 10 * 1024 * 1024


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: UUID | None = None
    filters: RetrievalFilters | None = None
    request_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("Question must not be blank")
        return question


class QuestionSource(BaseModel):
    citation: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    mime_type: str | None = None
    title: str | None = Field(default=None, exclude_if=lambda value: value is None)
    source_url: str | None = None
    source_file_version_id: UUID | None = None
    chunk_index: int
    page_start: int | None = None
    page_end: int | None = None
    cosine_distance: float | None


class QuestionResponse(BaseModel):
    answer: str
    sources: list[QuestionSource]
    conversation_id: UUID
    grounding: GroundedResult | None = Field(default=None, exclude_if=lambda value: value is None)


def question_fingerprint(request: QuestionRequest) -> str:
    # Preserve fingerprints written before request_id and metadata filters were added.
    excluded = {"request_id"}
    if request.filters is None or not request.filters.model_dump(exclude_none=True):
        excluded.add("filters")
    return sha256(request.model_dump_json(exclude=excluded).encode()).hexdigest()


@router.post("/questions", response_model=QuestionResponse)
def answer_question_request(
    request: QuestionRequest,
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    http_response: Response = None,
) -> QuestionResponse:
    token = None
    if current.get() is None and request.request_id is not None:
        token = current.set(ProgressContext(request.request_id, question_fingerprint(request), Event(), lambda _: None))
    try:
        return _answer_question_request(request, authenticated_user, http_response)
    finally:
        if token is not None:
            current.reset(token)


def _answer_question_request(
    request: QuestionRequest, authenticated_user: AuthenticatedUser, http_response: Response | None,
) -> QuestionResponse:
    received_at = datetime.now(timezone.utc)
    session = SessionLocal()
    guard = ExitStack()
    execution = QuestionExecution()
    execution_token = current_execution.set(execution)
    attempt = None
    try:
        guard.enter_context(request_guard(session, authenticated_user.id))
        progress = current.get()
        if progress is not None:
            saved = session.get(Message, message_id(authenticated_user.id, "assistant"))
            if saved is not None:
                user_message = session.get(Message, message_id(authenticated_user.id, "user"))
                owned = get_owned_conversation(session, saved.conversation_id, authenticated_user.id)
                expected = [{"request_fingerprint": progress.fingerprint}]
                if owned is None or user_message is None or user_message.citations != expected:
                    raise HTTPException(status_code=409, detail="Question request does not match")
                notify("validation")
                cleaned = expire_legacy_grounding(saved)
                replay = QuestionResponse(
                    answer=saved.content,
                    sources=saved.citations or [],
                    conversation_id=saved.conversation_id,
                )
                if cleaned:
                    check_connected()
                    session.commit()
                return replay
        conversation = None
        if request.conversation_id is not None:
            conversation = get_owned_conversation(
                session, request.conversation_id, authenticated_user.id
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found")

        try:
            attempt = begin_turn(
                session, authenticated_user.id, progress.request_id if progress else uuid4(),
                progress.fingerprint if progress else question_fingerprint(request), received_at,
            )
        except RequestFingerprintConflict as error:
            raise HTTPException(status_code=409, detail="Question request does not match") from error
        except PriorResponseDeleted as error:
            raise HTTPException(status_code=410, detail="Question response was deleted") from error

        if conversation is None:
            result = answer_question(
                session,
                request.question,
                top_k=request.top_k,
                **({"filters": request.filters} if request.filters is not None else {}),
            )
        else:
            history = list_recent_owned_messages(
                session,
                conversation.id,
                authenticated_user.id,
            )
            result = answer_question(
                session,
                request.question,
                top_k=request.top_k,
                history=history,
                **({"filters": request.filters} if request.filters is not None else {}),
            )
        notify("validation")
        sources = [
            QuestionSource(
                citation=citation,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                title=chunk.title,
                mime_type=chunk.mime_type,
                source_url=chunk.source_url,
                source_file_version_id=chunk.source_file_version_id,
                chunk_index=chunk.chunk_index,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                cosine_distance=chunk.cosine_distance,
            )
            for citation, chunk in enumerate(result.sources, start=1)
            if (
                result.cited_source_indices is None
                or citation in result.cited_source_indices
            )
        ]
        user_message_time = datetime.now(timezone.utc)
        assistant_message_time = user_message_time + timedelta(microseconds=1)
        if conversation is None:
            conversation = Conversation(
                id=message_id(authenticated_user.id, "conversation") or uuid4(),
                user_id=authenticated_user.id,
                title=create_title_from_question(request.question),
                is_pinned=False,
                created_at=user_message_time,
                updated_at=assistant_message_time,
            )
            session.add(conversation)
        else:
            conversation = update_owned_conversation(
                session,
                conversation.id,
                authenticated_user.id,
                updated_at=assistant_message_time,
            )
            if conversation is None:
                session.rollback()
                finish_rolled_back_turn(session, attempt, execution)
                attempt = None
                raise HTTPException(status_code=404, detail="Conversation not found")

        assistant_id = message_id(authenticated_user.id, "assistant") or uuid4()
        session.add_all(
            [
                Message(
                    id=message_id(authenticated_user.id, "user") or uuid4(),
                    conversation_id=conversation.id,
                    role="user",
                    content=request.question,
                    citations=[{"request_fingerprint": progress.fingerprint}] if progress else None,
                    created_at=user_message_time,
                ),
                Message(
                    id=assistant_id,
                    conversation_id=conversation.id,
                    role="assistant",
                    content=expire_grounded_text(result.answer) if result.grounding else result.answer,
                    citations=[source.model_dump(mode="json") for source in sources],
                    created_at=assistant_message_time,
                ),
            ]
        )
        response = QuestionResponse(
            answer=result.answer,
            sources=sources,
            conversation_id=conversation.id,
            grounding=result.grounding,
        )
        if http_response is not None and result.grounding:
            http_response.headers["Cache-Control"] = "no-store"
        check_connected()
        complete_turn(session, attempt, execution, assistant_id, result.resolution,
                      citations_validated=result.cited_source_indices is not None)
        check_connected()
        session.commit()
        return response
    except QuestionCancelled:
        session.rollback()
        finish_rolled_back_turn(session, attempt, execution)
        raise
    except HTTPException:
        if attempt is not None:
            session.rollback()
            finish_rolled_back_turn(session, attempt, execution)
        raise
    except QueryProcessingError as error:
        session.rollback()
        finish_rolled_back_turn(session, attempt, execution, failure_reason=(
            "provider_error" if error.category in {"provider", "timeout"} else "query_processing_error"
        ))
        raise HTTPException(
            status_code=503, detail="Question processing is unavailable"
        ) from error
    except (
        SQLAlchemyError,
        APIError,
        GoogleGenerativeAIError,
        TimeoutError,
        RuntimeError,
        ValueError,
    ) as error:
        session.rollback()
        reason = "answer_processing_error"
        if isinstance(error, SQLAlchemyError):
            reason = "database_error"
        elif isinstance(error, (APIError, GoogleGenerativeAIError, ProviderCallError, TimeoutError)):
            reason = "provider_error"
        finish_rolled_back_turn(session, attempt, execution, failure_reason=reason)
        raise HTTPException(
            status_code=503, detail="Question answering is unavailable"
        ) from error
    except Exception:
        session.rollback()
        finish_rolled_back_turn(session, attempt, execution, failure_reason="unexpected_error")
        raise
    finally:
        current_execution.reset(execution_token)
        try:
            session.close()
        finally:
            guard.close()


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def upload_document(
    file: UploadFile | None = File(default=None),
    category: Annotated[MetadataValue, Form()] = None,
    audience: Annotated[MetadataValue, Form()] = None,
) -> dict[str, str | int]:
    if file is None or not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported MIME type")

    content = file.file.read(MAX_FILE_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="File must not be empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MiB")

    session = SessionLocal()
    try:
        metadata = {key: value for key, value in {"category": category, "audience": audience}.items() if value is not None}
        document = ingest_document(session, file.filename, file.content_type, content, **metadata)
        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "chunk_count": len(document.chunks),
        }
    except (OCRUnavailable, OCRFailed) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    except (GoogleGenerativeAIError, RuntimeError, OSError) as error:
        raise HTTPException(status_code=503, detail="Ingestion is unavailable") from error
    finally:
        session.close()
