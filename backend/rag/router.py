from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from langchain_google_genai._common import GoogleGenerativeAIError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

from auth import AuthenticatedUser, get_authenticated_user, require_admin
from database import SessionLocal
from rag.ingestion import ingest_document
from rag.qa import answer_question


router = APIRouter()
ALLOWED_MIME_TYPES = {"application/pdf", "text/plain"}
MAX_FILE_SIZE = 10 * 1024 * 1024


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    top_k: int = Field(default=5, ge=1, le=20)

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
    chunk_index: int
    cosine_distance: float


class QuestionResponse(BaseModel):
    answer: str
    sources: list[QuestionSource]


@router.post("/questions", response_model=QuestionResponse)
def answer_question_request(
    request: QuestionRequest,
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> QuestionResponse:
    _ = authenticated_user.id
    session = SessionLocal()
    try:
        result = answer_question(session, request.question, top_k=request.top_k)
        return QuestionResponse(
            answer=result.answer,
            sources=[
                QuestionSource(
                    citation=citation,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    chunk_index=chunk.chunk_index,
                    cosine_distance=chunk.cosine_distance,
                )
                for citation, chunk in enumerate(result.sources, start=1)
            ],
        )
    except (
        SQLAlchemyError,
        GoogleGenerativeAIError,
        RuntimeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=503, detail="Question answering is unavailable"
        ) from error
    finally:
        session.close()


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def upload_document(
    file: UploadFile | None = File(default=None),
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
        document = ingest_document(session, file.filename, file.content_type, content)
        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "chunk_count": len(document.chunks),
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    finally:
        session.close()
