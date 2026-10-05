from __future__ import annotations

import logging
import time
from typing import Sequence

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai._common import GoogleGenerativeAIError
from pydantic import SecretStr, ValidationError

from rag.query_contract import (
    QUERY_PROCESSING_MODEL,
    QUERY_PROCESSING_SYSTEM_INSTRUCTION,
    HistoryMessage,
    QueryDecision,
    QueryProcessingResult,
)
from rag.provider_errors import (
    exception_chain,
    provider_error_kind,
    provider_status_code,
)


LOGGER = logging.getLogger("uvicorn.error")
QUERY_PROCESSING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            QUERY_PROCESSING_SYSTEM_INSTRUCTION,
        ),
        (
            "human",
            "Conversation history (may be empty):\n{history}\n\n"
            "Current question:\n{question}",
        ),
    ]
)


class QueryProcessingError(RuntimeError):
    """Raised with safe diagnostics when query processing cannot complete."""

    def __init__(
        self,
        message: str = "Query processing failed",
        *,
        cause_type: str = "unknown",
        category: str = "unknown",
        provider_error_kind: str | None = None,
        provider_status_code: int | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_stage = "query_processing"
        self.cause_type = cause_type
        self.category = category
        self.provider_error_kind = provider_error_kind
        self.provider_status_code = provider_status_code
        self.elapsed_ms = elapsed_ms


def _error_category(error: BaseException) -> str:
    chain = exception_chain(error)
    if any(isinstance(item, TimeoutError) for item in chain):
        return "timeout"
    if any(isinstance(item, ValidationError) for item in chain):
        return "schema_validation"
    if any(isinstance(item, GoogleGenerativeAIError) for item in chain):
        return "provider"
    return "unknown"


def _get_query_model() -> ChatGoogleGenerativeAI:
    from config import settings

    api_key: SecretStr | None = settings.gemini_api_key
    if api_key is None or not api_key.get_secret_value():
        raise RuntimeError("GEMINI_API_KEY is required for query processing")
    return ChatGoogleGenerativeAI(model=QUERY_PROCESSING_MODEL, api_key=api_key)


def _format_history(history: Sequence[HistoryMessage]) -> str:
    if not history:
        return "(empty)"
    return "\n".join(f"{message.role}: {message.content}" for message in history)


def process_query(
    question: str,
    history: Sequence[HistoryMessage] = (),
) -> QueryProcessingResult:
    started_at = time.perf_counter()
    history_used = bool(history)
    try:
        structured_model = _get_query_model().with_structured_output(QueryDecision)
        prompt = QUERY_PROCESSING_PROMPT.invoke(
            {"history": _format_history(history), "question": question}
        )
        raw_decision = structured_model.invoke(prompt)
        decision = (
            raw_decision
            if isinstance(raw_decision, QueryDecision)
            else QueryDecision.model_validate(raw_decision)
        )
    except (GoogleGenerativeAIError, RuntimeError, ValueError, TimeoutError) as error:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        category = _error_category(error)
        error_kind = provider_error_kind(error)
        status_code = provider_status_code(error)
        LOGGER.info(
            "[RAG] query processing error history_used=%s history_messages=%d "
            "elapsed_ms=%.2f exception=%s category=%s provider_error_kind=%s "
            "provider_status_code=%s",
            history_used,
            len(history),
            elapsed_ms,
            type(error).__name__,
            category,
            error_kind,
            status_code,
        )
        raise QueryProcessingError(
            cause_type=type(error).__name__,
            category=category,
            provider_error_kind=error_kind,
            provider_status_code=status_code,
            elapsed_ms=elapsed_ms,
        ) from error

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    LOGGER.info(
        "[RAG] query processing complete action=%s history_used=%s "
        "history_messages=%d elapsed_ms=%.2f",
        decision.action,
        history_used,
        len(history),
        elapsed_ms,
    )
    return QueryProcessingResult(
        action=decision.action,
        standalone_query=decision.standalone_query,
        clarification=decision.clarification,
        history_used=history_used,
        elapsed_ms=elapsed_ms,
    )
