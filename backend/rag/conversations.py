from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from rag.models import Conversation, Message
from rag.query_contract import (
    HISTORY_MAX_CHARACTERS,
    HISTORY_MAX_MESSAGES,
    HISTORY_MAX_TURNS,
    WEB_ANSWER_LABEL,
    HistoryMessage,
)


AUTO_TITLE_MAX_LENGTH = 80
GROUNDING_EXPIRED = "Kết quả tra cứu web đã hết hạn khi xem lại cuộc trò chuyện."


def expire_grounded_text(answer: str) -> str:
    return f"{answer}\n\n{GROUNDING_EXPIRED}" if answer else GROUNDING_EXPIRED


def expire_legacy_grounding(message: Message) -> bool:
    """Discard persisted grounding from the earlier combined answer format."""
    citations = getattr(message, "citations", None) or []
    if message.role != "assistant" or not any(
        isinstance(source, dict) and source.get("kind") == "web" for source in citations
    ):
        return False
    prefix, marker, _ = message.content.partition(f"**{WEB_ANSWER_LABEL}**\n\n")
    message.content = expire_grounded_text(prefix.rstrip() if marker else "")
    message.citations = [
        source for source in citations if isinstance(source, dict) and source.get("kind") != "web"
    ]
    return True


def create_title_from_question(question: str) -> str:
    normalized = " ".join(question.split())
    if len(normalized) <= AUTO_TITLE_MAX_LENGTH:
        return normalized
    return f"{normalized[: AUTO_TITLE_MAX_LENGTH - 1].rstrip()}…"


def list_owned_conversations(
    session: Session, user_id: UUID
) -> list[Conversation]:
    statement = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(
            Conversation.is_pinned.desc(),
            Conversation.updated_at.desc(),
        )
    )
    return list(session.scalars(statement))


def get_owned_conversation(
    session: Session, conversation_id: UUID, user_id: UUID
) -> Conversation | None:
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    )
    return session.scalar(statement)


def list_owned_messages(
    session: Session, conversation_id: UUID, user_id: UUID
) -> list[Message] | None:
    if get_owned_conversation(session, conversation_id, user_id) is None:
        return None

    statement = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.conversation_id == conversation_id)
        .where(Conversation.user_id == user_id)
        .order_by(Message.created_at.asc())
    )
    return list(session.scalars(statement))


def list_recent_owned_messages(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    max_messages: int = HISTORY_MAX_MESSAGES,
    max_characters: int = HISTORY_MAX_CHARACTERS,
) -> list[HistoryMessage]:
    statement = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.conversation_id == conversation_id)
        .where(Conversation.user_id == user_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    newest_first = list(session.scalars(statement))[:max_messages]
    messages = []
    for message in reversed(newest_first):
        if message.role not in {"user", "assistant"}:
            continue
        expire_legacy_grounding(message)
        content = message.content
        if message.role == "assistant" and content.endswith(GROUNDING_EXPIRED):
            content = content.removesuffix(GROUNDING_EXPIRED).rstrip()
        if content.strip():
            messages.append(HistoryMessage(role=message.role, content=content))

    while len(messages) > 2 and sum(len(item.content) for item in messages) > max_characters:
        remove_count = (
            2
            if messages[0].role == "user" and messages[1].role == "assistant"
            else 1
        )
        del messages[:remove_count]

    if messages and sum(len(item.content) for item in messages) > max_characters:
        remaining = max_characters
        bounded: list[HistoryMessage] = []
        for index, message in enumerate(messages):
            messages_left = len(messages) - index
            allowance = remaining // messages_left
            if allowance <= 0:
                break
            content = message.content[:allowance]
            bounded.append(HistoryMessage(role=message.role, content=content))
            remaining -= len(content)
        messages = bounded

    return messages


def update_owned_conversation(
    session: Session,
    conversation_id: UUID,
    user_id: UUID,
    *,
    title: str | None = None,
    is_pinned: bool | None = None,
    updated_at: datetime,
) -> Conversation | None:
    values: dict[str, object] = {"updated_at": updated_at}
    if title is not None:
        values["title"] = title
    if is_pinned is not None:
        values["is_pinned"] = is_pinned

    statement = (
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .values(**values)
        .returning(Conversation)
    )
    return session.scalar(statement)


def delete_owned_conversation(
    session: Session, conversation_id: UUID, user_id: UUID
) -> bool:
    statement = (
        delete(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .returning(Conversation.id)
    )
    return session.scalar(statement) is not None
