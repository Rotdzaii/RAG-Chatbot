"""Authenticated access to immutable originals cited in a user's conversation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from auth import AuthenticatedUser, get_authenticated_user
from config import settings
from database import SessionLocal
from rag.models import Conversation, Message, SourceFileVersion
from rag.source_files import read_version


router = APIRouter()
_MEDIA_TYPES = {"application/pdf": "source.pdf", "text/plain": "source.txt"}


@router.get("/source-files/{version_id}")
def open_source_file(
    version_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> Response:
    session = SessionLocal()
    try:
        version = session.get(SourceFileVersion, version_id)
        if version is None or version.mime_type not in _MEDIA_TYPES:
            raise HTTPException(status_code=404, detail="Source file not found")
        if user.id != getattr(settings, "admin_user_id", None):
            owned_citation = session.scalar(
                select(Message.id)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.user_id == user.id)
                .where(Message.role == "assistant")
                .where(Message.citations.contains([
                    {
                        "source_file_version_id": str(version_id),
                        "document_id": str(version.document_id),
                    }
                ]))
                .limit(1)
            )
            if owned_citation is None:
                # Do not disclose whether the version exists to another user.
                raise HTTPException(status_code=404, detail="Source file not found")
        try:
            content = read_version(
                version.id, version.mime_type, version.content_hash, version.byte_size
            )
        except OSError as error:
            raise HTTPException(status_code=503, detail="Source file is unavailable") from error
        return Response(
            content=content, media_type=version.mime_type,
            headers={
                "Content-Disposition": f'inline; filename="{_MEDIA_TYPES[version.mime_type]}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Source file is unavailable") from error
    finally:
        session.close()
