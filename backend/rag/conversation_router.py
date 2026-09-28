from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError

from auth import AuthenticatedUser, get_authenticated_user
from database import SessionLocal
from rag.conversations import (
    delete_owned_conversation,
    list_owned_conversations,
    list_owned_messages,
    update_owned_conversation,
)
from rag.models import Conversation


router = APIRouter(prefix="/conversations", tags=["conversations"])
MAX_TITLE_LENGTH = 200


def _validate_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ValueError("Title must not be blank")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Title must not exceed {MAX_TITLE_LENGTH} characters")
    return title


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str

    _trim_title = field_validator("title")(_validate_title)


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    is_pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Title must not be null")
        return _validate_title(value)

    @field_validator("is_pinned")
    @classmethod
    def validate_is_pinned(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("is_pinned must not be null")
        return value

    @model_validator(mode="after")
    def require_update(self) -> "ConversationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class ConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class MessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict[str, Any]] | None
    created_at: datetime


def _unavailable(_error: SQLAlchemyError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Conversation history is unavailable",
    )


@router.get("", response_model=list[ConversationItem])
def get_conversations(
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> list[ConversationItem]:
    session = SessionLocal()
    try:
        conversations = list_owned_conversations(session, authenticated_user.id)
        return [ConversationItem.model_validate(item) for item in conversations]
    except SQLAlchemyError as error:
        raise _unavailable(error) from error
    finally:
        session.close()


@router.post(
    "",
    response_model=ConversationItem,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: ConversationCreate,
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> ConversationItem:
    session = SessionLocal()
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        id=uuid4(),
        user_id=authenticated_user.id,
        title=request.title,
        is_pinned=False,
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(conversation)
        session.commit()
        return ConversationItem.model_validate(conversation)
    except SQLAlchemyError as error:
        session.rollback()
        raise _unavailable(error) from error
    finally:
        session.close()


@router.patch("/{conversation_id}", response_model=ConversationItem)
def patch_conversation(
    conversation_id: UUID,
    request: ConversationUpdate,
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> ConversationItem:
    session = SessionLocal()
    try:
        conversation = update_owned_conversation(
            session,
            conversation_id,
            authenticated_user.id,
            title=request.title,
            is_pinned=request.is_pinned,
            updated_at=datetime.now(timezone.utc),
        )
        if conversation is None:
            session.rollback()
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.commit()
        return ConversationItem.model_validate(conversation)
    except SQLAlchemyError as error:
        session.rollback()
        raise _unavailable(error) from error
    finally:
        session.close()


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_conversation(
    conversation_id: UUID,
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> Response:
    session = SessionLocal()
    try:
        if not delete_owned_conversation(
            session, conversation_id, authenticated_user.id
        ):
            session.rollback()
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except SQLAlchemyError as error:
        session.rollback()
        raise _unavailable(error) from error
    finally:
        session.close()


@router.get("/{conversation_id}/messages", response_model=list[MessageItem])
def get_conversation_messages(
    conversation_id: UUID,
    authenticated_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> list[MessageItem]:
    session = SessionLocal()
    try:
        messages = list_owned_messages(
            session, conversation_id, authenticated_user.id
        )
        if messages is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return [MessageItem.model_validate(item) for item in messages]
    except SQLAlchemyError as error:
        raise _unavailable(error) from error
    finally:
        session.close()
