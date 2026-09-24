import logging
import time
from threading import Lock
from typing import Any, Sequence
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult


LOGGER = logging.getLogger("uvicorn.error")

_CHAIN_STAGES = {
    "sqlalchemy_rag_pipeline": "pipeline",
    "retrieve_context": "retrieval",
    "answer_from_context": "answer selection",
    "create_generation_chain": "generation",
    "generate_grounded_answer": "generation",
    "format_numbered_context": "context formatting",
    "grounded_answer_prompt": "prompt formatting",
    "parse_model_answer": "output parsing",
    "validate_model_answer": "answer validation",
}
_COMPLETION_STAGES = {
    "pipeline",
    "context formatting",
    "prompt formatting",
    "output parsing",
}


class LangChainTraceHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self._runs: dict[UUID, tuple[str, float]] = {}
        self._lock = Lock()

    @staticmethod
    def _short_run_id(run_id: UUID) -> str:
        return run_id.hex[-8:]

    def _start(self, run_id: UUID, stage: str) -> None:
        started_at = time.perf_counter()
        with self._lock:
            self._runs[run_id] = (stage, started_at)

    def _finish(self, run_id: UUID) -> tuple[str, float] | None:
        finished_at = time.perf_counter()
        with self._lock:
            run = self._runs.pop(run_id, None)
        if run is None:
            return None
        stage, started_at = run
        return stage, (finished_at - started_at) * 1000

    def _log_error(self, run_id: UUID, error: BaseException, fallback: str) -> None:
        run = self._finish(run_id)
        stage = run[0] if run is not None else fallback
        LOGGER.info(
            "[LangChain] %s error run=%s exception=%s",
            stage,
            self._short_run_id(run_id),
            type(error).__name__,
        )

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name")
        if not isinstance(name, str):
            name = serialized.get("name") if serialized else None
        stage = _CHAIN_STAGES.get(name)
        if stage is None:
            return

        self._start(run_id, stage)
        if stage == "pipeline":
            LOGGER.info(
                "[LangChain] pipeline start run=%s", self._short_run_id(run_id)
            )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        run = self._finish(run_id)
        if run is None:
            return
        stage, elapsed_ms = run
        if stage in _COMPLETION_STAGES:
            LOGGER.info(
                "[LangChain] %s %s run=%s elapsed_ms=%.2f",
                stage,
                "end" if stage == "pipeline" else "complete",
                self._short_run_id(run_id),
                elapsed_ms,
            )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            is_tracked = run_id in self._runs
        if is_tracked:
            self._log_error(run_id, error, "chain")

    def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start(run_id, "retriever")
        LOGGER.info(
            "[LangChain] retriever start run=%s", self._short_run_id(run_id)
        )

    def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        run = self._finish(run_id)
        if run is None:
            return
        _, elapsed_ms = run
        LOGGER.info(
            "[LangChain] retriever end run=%s documents=%d elapsed_ms=%.2f",
            self._short_run_id(run_id),
            len(documents),
            elapsed_ms,
        )

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._log_error(run_id, error, "retriever")

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start(run_id, "chat model")
        LOGGER.info(
            "[LangChain] chat model start run=%s", self._short_run_id(run_id)
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        run = self._finish(run_id)
        if run is None:
            return
        _, elapsed_ms = run
        LOGGER.info(
            "[LangChain] chat model end run=%s elapsed_ms=%.2f",
            self._short_run_id(run_id),
            elapsed_ms,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._log_error(run_id, error, "chat model")
