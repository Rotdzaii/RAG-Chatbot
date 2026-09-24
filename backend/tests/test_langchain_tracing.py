from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy.orm import Session


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test",
    rag_trace_enabled=False,
)
sys.modules.setdefault("config", fake_config)

from rag.qa import QuestionAnswer, answer_question  # noqa: E402
from rag.retrieval import RetrievedChunk  # noqa: E402
from rag.tracing import LangChainTraceHandler  # noqa: E402


QUESTION = "sensitive question text"
PAGE_CONTENT = "sensitive page content"
MODEL_ANSWER = "sensitive model answer"
EXCEPTION_MESSAGE = "sensitive exception message"
FAKE_API_KEY = "fake-api-key-never-log"


def runtime_config(trace_enabled: bool) -> ModuleType:
    module = ModuleType("config")
    module.settings = SimpleNamespace(rag_trace_enabled=trace_enabled)
    return module


def pipeline_result() -> dict[str, object]:
    return {
        "answer": "Answer [1]",
        "documents": [
            Document(
                page_content="Reference content.",
                metadata={
                    "chunk_id": str(uuid4()),
                    "document_id": str(uuid4()),
                    "filename": "guide.txt",
                    "chunk_index": 2,
                    "cosine_distance": 0.12,
                },
            )
        ],
    }


class TraceAttachmentTests(unittest.TestCase):
    def test_disabled_tracing_does_not_attach_callback(self) -> None:
        session = Mock()
        pipeline = Mock()
        pipeline.invoke.return_value = pipeline_result()

        with (
            patch.dict(sys.modules, {"config": runtime_config(False)}),
            patch("rag.qa.build_rag_pipeline", return_value=pipeline),
            patch("rag.qa.LangChainTraceHandler") as handler_class,
        ):
            result = answer_question(session, "Question")

        self.assertIsInstance(result, QuestionAnswer)
        self.assertEqual(result.answer, "Answer [1]")
        self.assertEqual(result.sources[0].filename, "guide.txt")
        handler_class.assert_not_called()
        pipeline.invoke.assert_called_once_with({"question": "Question"})

    def test_enabled_tracing_attaches_exactly_one_callback(self) -> None:
        session = Mock()
        pipeline = Mock()
        pipeline.invoke.return_value = pipeline_result()

        with (
            patch.dict(sys.modules, {"config": runtime_config(True)}),
            patch("rag.qa.build_rag_pipeline", return_value=pipeline),
            patch("rag.qa.LangChainTraceHandler") as handler_class,
        ):
            result = answer_question(session, "Question")

        self.assertIsInstance(result, QuestionAnswer)
        self.assertEqual(result.answer, "Answer [1]")
        self.assertEqual(result.sources[0].filename, "guide.txt")
        handler_class.assert_called_once_with()
        pipeline.invoke.assert_called_once_with(
            {"question": "Question"},
            config={"callbacks": [handler_class.return_value]},
        )

    def test_callback_reaches_lazy_generation_chain_without_changing_result(
        self,
    ) -> None:
        session = Mock(spec=Session)
        chunk = RetrievedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            filename="guide.txt",
            chunk_index=2,
            content=PAGE_CONTENT,
            cosine_distance=0.12,
        )
        model = RunnableLambda(lambda _: AIMessage(content="Answer [1]"))

        with (
            patch.dict(sys.modules, {"config": runtime_config(True)}),
            patch(
                "rag.langchain_retriever.retrieve_chunks", return_value=[chunk]
            ),
            patch("rag.langchain_pipeline._get_chat_model", return_value=model),
            self.assertLogs("uvicorn.error", level="INFO") as captured,
        ):
            result = answer_question(session, QUESTION)

        logs = "\n".join(captured.output)
        self.assertEqual(result.answer, "Answer [1]")
        self.assertEqual(result.sources, [chunk])
        self.assertIn("[LangChain] pipeline start", logs)
        self.assertIn("[LangChain] retriever end", logs)
        self.assertIn("[LangChain] context formatting complete", logs)
        self.assertIn("[LangChain] prompt formatting complete", logs)
        self.assertIn("[LangChain] output parsing complete", logs)
        self.assertIn("[LangChain] pipeline end", logs)
        self.assertNotIn(QUESTION, logs)
        self.assertNotIn(PAGE_CONTENT, logs)
        self.assertNotIn("Answer [1]", logs)


class TraceHandlerLoggingTests(unittest.TestCase):
    def assert_sanitized(self, logs: str) -> None:
        for secret in (
            QUESTION,
            PAGE_CONTENT,
            MODEL_ANSWER,
            EXCEPTION_MESSAGE,
            FAKE_API_KEY,
        ):
            self.assertNotIn(secret, logs)

    def test_retriever_logs_count_and_elapsed_time_without_payloads(self) -> None:
        handler = LangChainTraceHandler()
        run_id = uuid4()
        documents = [
            Document(page_content=PAGE_CONTENT),
            Document(page_content=f"{PAGE_CONTENT} two"),
        ]

        with (
            patch("rag.tracing.time.perf_counter", side_effect=[10.0, 10.025]),
            self.assertLogs("uvicorn.error", level="INFO") as captured,
        ):
            handler.on_retriever_start(
                {}, f"{QUESTION} {FAKE_API_KEY}", run_id=run_id
            )
            handler.on_retriever_end(documents, run_id=run_id)

        logs = "\n".join(captured.output)
        self.assertIn("[LangChain] retriever start", logs)
        self.assertIn("[LangChain] retriever end", logs)
        self.assertIn("documents=2", logs)
        self.assertIn("elapsed_ms=25.00", logs)
        self.assert_sanitized(logs)

    def test_model_callbacks_log_stages_without_messages_or_answers(self) -> None:
        handler = LangChainTraceHandler()
        run_id = uuid4()
        messages = [[HumanMessage(content=f"{QUESTION} {FAKE_API_KEY}")]]
        response = Mock(answer=MODEL_ANSWER)

        with (
            patch("rag.tracing.time.perf_counter", side_effect=[20.0, 20.01]),
            self.assertLogs("uvicorn.error", level="INFO") as captured,
        ):
            handler.on_chat_model_start({}, messages, run_id=run_id)
            handler.on_llm_end(response, run_id=run_id)

        logs = "\n".join(captured.output)
        self.assertIn("[LangChain] chat model start", logs)
        self.assertIn("[LangChain] chat model end", logs)
        self.assertIn("elapsed_ms=10.00", logs)
        self.assert_sanitized(logs)

    def test_chain_completion_and_errors_are_sanitized(self) -> None:
        handler = LangChainTraceHandler()
        pipeline_run = uuid4()
        context_run = uuid4()
        prompt_run = uuid4()
        parser_run = uuid4()
        error_run = uuid4()

        with (
            patch(
                "rag.tracing.time.perf_counter",
                side_effect=[
                    1.0,
                    1.01,
                    2.0,
                    2.01,
                    3.0,
                    3.01,
                    4.0,
                    4.01,
                    5.0,
                    5.01,
                ],
            ),
            self.assertLogs("uvicorn.error", level="INFO") as captured,
        ):
            handler.on_chain_start(
                {}, {"question": QUESTION}, run_id=pipeline_run,
                name="sqlalchemy_rag_pipeline"
            )
            handler.on_chain_end(
                {"answer": MODEL_ANSWER}, run_id=pipeline_run
            )
            handler.on_chain_start(
                {}, {"documents": [PAGE_CONTENT]}, run_id=context_run,
                name="format_numbered_context"
            )
            handler.on_chain_end({"context": PAGE_CONTENT}, run_id=context_run)
            handler.on_chain_start(
                {}, {"context": PAGE_CONTENT}, run_id=prompt_run,
                name="grounded_answer_prompt"
            )
            handler.on_chain_end({"prompt": QUESTION}, run_id=prompt_run)
            handler.on_chain_start(
                {}, {"answer": MODEL_ANSWER}, run_id=parser_run,
                name="parse_model_answer"
            )
            handler.on_chain_end({"answer": MODEL_ANSWER}, run_id=parser_run)
            handler.on_retriever_start({}, QUESTION, run_id=error_run)
            handler.on_retriever_error(
                RuntimeError(f"{EXCEPTION_MESSAGE} {FAKE_API_KEY}"),
                run_id=error_run,
            )

        logs = "\n".join(captured.output)
        self.assertIn("[LangChain] pipeline start", logs)
        self.assertIn("[LangChain] pipeline end", logs)
        self.assertIn("[LangChain] context formatting complete", logs)
        self.assertIn("[LangChain] prompt formatting complete", logs)
        self.assertIn("[LangChain] output parsing complete", logs)
        self.assertIn("retriever error", logs)
        self.assertIn("exception=RuntimeError", logs)
        self.assert_sanitized(logs)


if __name__ == "__main__":
    unittest.main()
