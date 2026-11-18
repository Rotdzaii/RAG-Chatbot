"""Operational outcomes and routes, without question or answer content."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class Outcome(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient_evidence"
    CLARIFY = "clarification"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    reasons: tuple[str, ...] = ()


def combine_resolutions(parts: list[Resolution]) -> Resolution:
    outcomes = {part.outcome for part in parts}
    reasons = tuple(sorted({reason for part in parts for reason in part.reasons}))
    if outcomes == {Outcome.ANSWERED}:
        return Resolution(Outcome.ANSWERED, reasons)
    if outcomes & {Outcome.ANSWERED, Outcome.PARTIAL}:
        return Resolution(Outcome.PARTIAL, reasons)
    for outcome in (Outcome.ERROR, Outcome.CLARIFY, Outcome.UNAVAILABLE, Outcome.INSUFFICIENT):
        if outcome in outcomes:
            return Resolution(outcome, reasons)
    raise ValueError("Question has no operational outcome")


Route = Literal["internal", "general", "web"]


@dataclass
class QuestionExecution:
    planned: set[Route] = field(default_factory=set)
    executed: set[Route] = field(default_factory=set)


current_execution: ContextVar[QuestionExecution | None] = ContextVar("question_execution", default=None)


def mark_executed(route: Route) -> None:
    execution = current_execution.get()
    if execution is not None:
        execution.executed.add(route)
