"""Durable, content-free telemetry for accepted question requests."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from rag.models import QuestionTurn
from rag.question_outcomes import Outcome, QuestionExecution, Resolution


LOGGER = logging.getLogger(__name__)
VALIDATED_CITATION_VERSION = 1


class RequestFingerprintConflict(Exception):
    pass


class PriorResponseDeleted(Exception):
    pass


@dataclass(frozen=True)
class QuestionAttempt:
    user_id: UUID
    request_id: UUID
    attempt_id: UUID


def begin_turn(
    caller: Session, user_id: UUID, request_id: UUID, fingerprint: str, received_at: datetime,
) -> QuestionAttempt | None:
    """Commit the start independently, while the caller owns the request guard."""
    attempt = QuestionAttempt(user_id, request_id, uuid4())
    try:
        with Session(caller.get_bind()) as session, session.begin():
            previous = session.get(QuestionTurn, (user_id, request_id), with_for_update=True)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise RequestFingerprintConflict()
                if previous.state == "completed":
                    raise PriorResponseDeleted()
                previous.attempt_id = attempt.attempt_id
                previous.state = "running"
                previous.finished_at = None
                previous.outcome = None
                previous.planned_routes = []
                previous.executed_routes = []
                previous.reasons = []
            else:
                session.add(QuestionTurn(
                    user_id=user_id, request_id=request_id, attempt_id=attempt.attempt_id,
                    fingerprint=fingerprint, received_at=received_at, state="running",
                    planned_routes=[], executed_routes=[], reasons=[],
                ))
    except (RequestFingerprintConflict, PriorResponseDeleted):
        raise
    except Exception:
        LOGGER.warning("Question statistics start could not be recorded")
        return None
    return attempt


def _finish(session: Session, attempt: QuestionAttempt, execution: QuestionExecution, *,
            state: str, resolution: Resolution | None, **response_fields) -> None:
    # A rollback releases the PostgreSQL guard before the independent update.
    # Match the attempt token so a late failure cannot clobber a newer retry.
    reasons = list(resolution.reasons) if resolution else []
    if state == "cancelled":
        reasons.append("request_cancelled")
    session.execute(
        update(QuestionTurn)
        .where(QuestionTurn.user_id == attempt.user_id, QuestionTurn.request_id == attempt.request_id,
               QuestionTurn.attempt_id == attempt.attempt_id, QuestionTurn.state == "running")
        .values(state=state, finished_at=datetime.now(timezone.utc),
                outcome=resolution.outcome if resolution else None,
                reasons=reasons,
                planned_routes=sorted(execution.planned), executed_routes=sorted(execution.executed),
                **response_fields)
    )


def complete_turn(
    session: Session, attempt: QuestionAttempt | None, execution: QuestionExecution,
    assistant_id: UUID, resolution: Resolution | None, *, citations_validated: bool,
) -> None:
    if attempt is None:
        return
    # Flush the real response before the savepoint. Its write failures must
    # still take the question's normal rollback path.
    session.flush()
    try:
        with session.begin_nested():
            _finish(session, attempt, execution, state="completed", resolution=resolution,
                    assistant_message_id=assistant_id,
                    citation_version=VALIDATED_CITATION_VERSION if citations_validated else None)
    except Exception:
        LOGGER.warning("Question statistics outcome could not be recorded")


def finish_rolled_back_turn(
    caller: Session, attempt: QuestionAttempt | None, execution: QuestionExecution, *,
    failure_reason: str | None = None,
) -> None:
    if attempt is None:
        return
    resolution = Resolution(Outcome.ERROR, (failure_reason,)) if failure_reason else None
    try:
        with Session(caller.get_bind()) as session, session.begin():
            _finish(session, attempt, execution, state="failed" if resolution else "cancelled",
                    resolution=resolution)
    except Exception:
        LOGGER.warning("Question statistics rollback could not be recorded")
