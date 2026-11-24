from collections.abc import Callable, Iterator, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import require_admin
from database import SessionLocal
from rag.models import Document, Message, QuestionTurn
from rag.question_outcomes import Outcome
from rag.question_tracking import VALIDATED_CITATION_VERSION


ADMIN_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_STATISTICS_DAYS = 31
ExecutedRoute = Literal["internal", "general", "web", "mixed", "none"]
EXECUTED_ROUTES = ("internal", "general", "web", "mixed", "none")
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class Measure(BaseModel):
    count: int | None
    ratio: float | None


class RankedDocument(Measure):
    count: int
    document_id: UUID
    filename: str | None
    deleted: bool


class DailyClassified(BaseModel):
    date: date
    count: int | None


class Statistics(BaseModel):
    start_date: date
    end_date: date
    timezone: str = ADMIN_TIMEZONE.key
    data_started_at: datetime | None
    outcome_denominator: int
    daily_classified: list[DailyClassified]
    unclassified: int
    running: int
    cancelled: int
    by_outcome: dict[Outcome, Measure]
    by_executed_route: dict[str, Measure]
    cited_answer_denominator: int
    ranked_documents: list[RankedDocument]


def _utc_boundary(day: date) -> datetime:
    return datetime.combine(day, time.min, ADMIN_TIMEZONE).astimezone(timezone.utc)


def _days(start: date, end: date) -> Iterator[date]:
    for offset in range((end - start).days):
        yield start + timedelta(days=offset)


def daily_classified_series(
    start: date, end: date, counts: Mapping[date, int], first_measured: date | None, last_measured: date,
) -> list[DailyClassified]:
    return [
        DailyClassified(date=day, count=counts.get(day, 0 if first_measured is not None
                                                   and first_measured <= day <= last_measured else None))
        for day in _days(start, end)
    ]


def _ratio(count: int, total: int) -> float | None:
    return count / total if total else None


def _tallies(counts: dict, total: int) -> dict:
    return {key: Measure(count=count if total else None, ratio=_ratio(count, total)) for key, count in counts.items()}


def _citation_pairs(session: Session, start: datetime, end: datetime):
    # Expand only typed citation arrays. SQLite supports the same report on
    # isolated fixtures using its native JSON functions.
    if session.get_bind().dialect.name == "sqlite":
        array = case((func.json_type(Message.citations) == "array", Message.citations), else_="[]")
        refs = func.json_each(array).table_valued("value", "type")
        value = case((refs.c.type == "object", refs.c.value), else_="{}")
        document_id = func.json_extract(value, "$.document_id")
        filename = func.json_extract(value, "$.filename")
        kind = func.json_extract(value, "$.kind")
    else:
        array = case((func.jsonb_typeof(Message.citations) == "array", Message.citations),
                     else_=cast("[]", JSONB))
        refs = func.jsonb_array_elements(array).table_valued("value")
        document_id = refs.c.value.op("->>")("document_id")
        filename = refs.c.value.op("->>")("filename")
        kind = refs.c.value.op("->>")("kind")
    key = func.lower(func.replace(document_id, "-", ""))
    return (
        select(Message.id.label("message_id"), Message.created_at, key.label("document_key"),
               func.max(func.nullif(filename, "")).label("citation_filename"))
        .select_from(Message)
        .join(QuestionTurn, QuestionTurn.assistant_message_id == Message.id)
        .join(refs, true())
        .where(Message.role == "assistant", Message.created_at >= start, Message.created_at < end,
               QuestionTurn.citation_version == VALIDATED_CITATION_VERSION,
               func.coalesce(kind, "document") == "document", key.regexp_match("^[0-9a-f]{32}$"))
        .group_by(Message.id, Message.created_at, key)
        .cte("citation_pairs")
    )


def _document_ranking(session: Session, start: datetime, end: datetime, limit: int):
    pairs = _citation_pairs(session, start, end)
    denominator = session.scalar(select(func.count(func.distinct(pairs.c.message_id)))) or 0
    ranked = select(
        pairs.c.document_key, pairs.c.citation_filename,
        func.count().over(partition_by=pairs.c.document_key).label("count"),
        func.row_number().over(
            partition_by=pairs.c.document_key,
            order_by=(pairs.c.created_at.desc(), pairs.c.message_id.desc()),
        ).label("position"),
    ).subquery()
    current_id = func.lower(func.replace(cast(Document.id, String), "-", ""))
    result = session.execute(
        select(ranked.c.document_key, ranked.c.count,
               func.coalesce(Document.filename, ranked.c.citation_filename).label("filename"),
               Document.id.is_(None).label("deleted"))
        .select_from(ranked)
        .outerjoin(Document, current_id == ranked.c.document_key)
        .where(ranked.c.position == 1)
        .order_by(ranked.c.count.desc(), ranked.c.document_key)
        .limit(limit)
    )
    return denominator, [
        RankedDocument(document_id=UUID(row.document_key), filename=row.filename, deleted=row.deleted,
                       count=row.count, ratio=_ratio(row.count, denominator))
        for row in result
    ]


def summarize(session: Session, start_date: date, end_date: date, limit: int) -> Statistics:
    start, end = _utc_boundary(start_date), _utc_boundary(end_date)
    outcomes = dict.fromkeys(Outcome, 0)
    routes = dict.fromkeys(EXECUTED_ROUTES, 0)
    running = cancelled = unclassified = 0
    days = list(_days(start_date, end_date))
    daily_counts: dict[date, int] = {}
    turn = QuestionTurn
    # UTC boundaries give the same local calendar buckets in PostgreSQL and SQLite.
    day_index = case(*[
        (turn.received_at < _utc_boundary(day + timedelta(days=1)), index)
        for index, day in enumerate(days)
    ]).label("day_index")
    grouped = session.execute(
        select(day_index, turn.state, turn.outcome, turn.executed_routes, func.count().label("count"))
        .where(turn.received_at >= start, turn.received_at < end)
        .group_by(day_index, turn.state, turn.outcome, turn.executed_routes)
    )
    for row in grouped:
        if row.state == "running":
            running += row.count
        elif row.state == "cancelled":
            cancelled += row.count
        elif row.outcome is None:
            unclassified += row.count
        else:
            outcomes[Outcome(row.outcome)] += row.count
            day = days[row.day_index]
            daily_counts[day] = daily_counts.get(day, 0) + row.count
            executed = row.executed_routes
            route = executed[0] if len(executed) == 1 else "mixed" if executed else "none"
            routes[route] += row.count
    unclassified += session.scalar(
        select(func.count()).select_from(Message)
        .where(Message.role == "assistant", Message.created_at >= start, Message.created_at < end,
               ~select(turn.assistant_message_id).where(turn.assistant_message_id == Message.id).exists())
    ) or 0
    started_at = session.scalar(select(func.min(turn.received_at)))
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    first_measured = started_at.astimezone(ADMIN_TIMEZONE).date() if started_at else None
    today = datetime.now(ADMIN_TIMEZONE).date()
    total = sum(outcomes.values())
    cited_total, documents = _document_ranking(session, start, end, limit)
    return Statistics(
        start_date=start_date, end_date=end_date, data_started_at=started_at,
        outcome_denominator=total, unclassified=unclassified, running=running, cancelled=cancelled,
        daily_classified=daily_classified_series(start_date, end_date, daily_counts, first_measured, today),
        by_outcome=_tallies(outcomes, total), by_executed_route=_tallies(routes, total),
        cited_answer_denominator=cited_total, ranked_documents=documents,
    )


def _load_database_statistics(start_date: date, end_date: date, limit: int) -> Statistics:
    try:
        with SessionLocal() as session:
            # All denominators and rankings see the same committed snapshot.
            if session.get_bind().dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            return summarize(session, start_date, end_date, limit)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Statistics are unavailable") from error
    except OverflowError as error:
        raise HTTPException(status_code=422, detail="Date range is outside supported bounds") from error


def get_statistics_loader() -> Callable[[date, date, int], Statistics]:
    return _load_database_statistics


@router.get("/statistics", response_model=Statistics)
def admin_statistics(
    start_date: Annotated[date, Query(alias="from")],
    end_date: Annotated[date, Query(alias="to")],
    load_statistics: Annotated[Callable[[date, date, int], Statistics], Depends(get_statistics_loader)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> Statistics:
    if start_date >= end_date:
        raise HTTPException(status_code=422, detail="from must precede to")
    if (end_date - start_date).days > MAX_STATISTICS_DAYS:
        raise HTTPException(status_code=422, detail="Statistics range must not exceed 31 days")
    return load_statistics(start_date, end_date, limit)
