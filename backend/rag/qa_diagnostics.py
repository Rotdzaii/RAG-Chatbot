"""Opt-in evidence observations for the local smoke runner."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from math import isfinite


@dataclass
class SearchObservation:
    major: str | None
    criterion: str | None
    subquestion: str
    query: str
    candidate_limit: int
    context_budget: int
    status: str = "planned"
    max_distance: float | None = None
    candidates: list[dict] = field(default_factory=list)

    def record_candidates(self, rows, returned, max_distance: float | None) -> None:
        """Audit every scoped vector against the actual limited SQL result."""
        self.max_distance = max_distance
        actual = {chunk.chunk_id: rank for rank, chunk in enumerate(returned, 1)}
        last_distance = returned[-1].cosine_distance if len(returned) == self.candidate_limit else None
        for rank, row in enumerate(rows, 1):
            distance = row["cosine_distance"]
            actual_rank = actual.get(row["chunk_id"])
            if actual_rank is not None:
                decision = "retrieved"
            elif distance is None or not isfinite(distance):
                decision = "invalid_distance"
                distance = None
            elif max_distance is not None and distance > max_distance:
                decision = "above_threshold"
            elif last_distance is not None and distance >= last_distance:
                decision = "outside_retrieval_budget"
            else:
                decision = "not_returned_by_retrieval"
            self.candidates.append({
                "chunk_id": str(row["chunk_id"]), "document_id": str(row["document_id"]),
                "filename": row["filename"], "chunk_index": row["chunk_index"],
                "rank": rank, "cosine_distance": distance, "retrieved_rank": actual_rank,
                "decision": decision, "citation": None,
            })
        self.status = "searched"

    def record_selection(self, citation_numbers: dict[str, int], eligible: set[str] | None = None) -> None:
        for candidate in self.candidates:
            if candidate["retrieved_rank"] is not None:
                chunk_id = candidate["chunk_id"]
                if eligible is not None and chunk_id not in eligible:
                    candidate["decision"] = "criterion_not_supported"
                    continue
                number = citation_numbers.get(chunk_id)
                candidate["citation"] = number
                candidate["decision"] = "selected" if number is not None else "outside_context_budget"


@dataclass
class QuestionDiagnostics:
    plan: dict = field(default_factory=dict)
    searches: list[SearchObservation] = field(default_factory=list)
    inventory: list[dict] = field(default_factory=list)


# LangChain propagates the execution context to its retrieval runnable.
current_search: ContextVar[SearchObservation | None] = ContextVar("qa_observed_search", default=None)


@contextmanager
def observe_search(trace: QuestionDiagnostics | None, major: str | None, criterion: str | None,
                   subquestion: str, query: str, *, candidate_limit: int, context_budget: int):
    observation = None
    if trace is not None:
        observation = SearchObservation(major, criterion, subquestion, query, candidate_limit, context_budget)
        trace.searches.append(observation)
    token = current_search.set(observation)
    try:
        yield observation
    finally:
        current_search.reset(token)
