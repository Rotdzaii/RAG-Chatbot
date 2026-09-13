from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal
from rag.ingestion import ingest_document


router = APIRouter()
ALLOWED_MIME_TYPES = {"application/pdf", "text/plain"}
MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/documents", status_code=status.HTTP_201_CREATED)
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
