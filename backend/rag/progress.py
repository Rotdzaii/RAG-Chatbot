"""Request-scoped progress and cancellation; no model/configuration changes."""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from threading import Event, Lock
from typing import Callable, Literal
from uuid import UUID, uuid5

from sqlalchemy import text

Stage = Literal["query", "retrieval", "generation", "validation"]


class QuestionCancelled(Exception):
    pass


@dataclass
class ProgressContext:
    request_id: UUID
    fingerprint: str
    cancelled: Event
    emit: Callable[[Stage], None]


current: ContextVar[ProgressContext | None] = ContextVar("question_progress", default=None)


def check_connected() -> None:
    context = current.get()
    if context is not None and context.cancelled.is_set():
        raise QuestionCancelled()


def notify(stage: Stage) -> None:
    check_connected()
    context = current.get()
    if context is not None:
        context.emit(stage)


def message_id(user_id: UUID, role: str) -> UUID | None:
    context = current.get()
    return uuid5(user_id, f"question:{context.request_id}:{role}") if context else None


# SQLite test fixtures need a process lock; PostgreSQL additionally serializes
# retries across workers with a transaction advisory lock. Entries are removed.
_guard = Lock()
_locks: dict[tuple[UUID, UUID], tuple[Lock, int]] = {}


@contextmanager
def request_guard(session, user_id: UUID):
    context = current.get()
    if context is None:
        yield
        return
    key = (user_id, context.request_id)
    with _guard:
        lock, users = _locks.get(key, (Lock(), 0))
        _locks[key] = (lock, users + 1)
    acquired = False
    try:
        while not acquired:
            check_connected()
            acquired = lock.acquire(timeout=0.1)
        if session.get_bind().dialect.name == "postgresql":
            digest = sha256(f"{user_id}:{context.request_id}".encode()).digest()
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(digest[:8], "big", signed=True)})
        check_connected()
        yield
    finally:
        if acquired:
            lock.release()
        with _guard:
            _, users = _locks[key]
            if users == 1:
                del _locks[key]
            else:
                _locks[key] = (lock, users - 1)
