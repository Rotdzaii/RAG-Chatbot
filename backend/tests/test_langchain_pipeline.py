from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import SecretStr
from sqlalchemy.orm import Session


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.langchain_pipeline import (  # noqa: E402
    MODEL,
    NO_CONTEXT_MESSAGE,
    _get_chat_model,
    build_rag_pipeline,
)
from rag.retrieval import RetrievedChunk  # noqa: E402


def retrieved_chunk(filename: str, index: int, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename=filename,
        chunk_index=index,
        content=content,
        cosine_distance=0.1,
    )


class LangChainPipelineTests(unittest.TestCase):
    def test_retrieves_once_and_generates_from_ordered_context(self) -> None:
        session = Mock(spec=Session)
        chunks = [
            retrieved_chunk("first.pdf", 3, "First context."),
            retrieved_chunk("second.txt", 8, "Second context."),
        ]
        captured_prompts: list[object] = []

        def respond(prompt: object) -> AIMessage:
            captured_prompts.append(prompt)
            return AIMessage(content="  Grounded answer [1] [2]  ")

        model = RunnableLambda(respond)
        with (
            patch(
                "rag.langchain_retriever.retrieve_chunks", return_value=chunks
            ) as retrieve,
            patch(
                "rag.langchain_pipeline._get_chat_model", return_value=model
            ) as get_model,
        ):
            result = build_rag_pipeline(session, top_k=2).invoke(
                {"question": "What are the requirements?"}
            )

        retrieve.assert_called_once_with(
            session, "What are the requirements?", top_k=2
        )
        get_model.assert_called_once_with()
        self.assertEqual(result["answer"], "Grounded answer [1] [2]")
        self.assertEqual(
            [document.page_content for document in result["documents"]],
            ["First context.", "Second context."],
        )

        messages = captured_prompts[0].to_messages()
        rendered_prompt = "\n".join(str(message.content) for message in messages)
        first_position = rendered_prompt.index("[1]\nFilename: first.pdf")
        second_position = rendered_prompt.index("[2]\nFilename: second.txt")
        self.assertLess(first_position, second_position)
        self.assertIn("Chunk index: 3", rendered_prompt)
        self.assertIn("First context.", rendered_prompt)
        self.assertIn("Chunk index: 8", rendered_prompt)
        self.assertIn("Second context.", rendered_prompt)
        self.assertIn("Question:\nWhat are the requirements?", rendered_prompt)

    def test_no_context_does_not_construct_or_invoke_model(self) -> None:
        session = Mock(spec=Session)

        with (
            patch(
                "rag.langchain_retriever.retrieve_chunks", return_value=[]
            ) as retrieve,
            patch("rag.langchain_pipeline._get_chat_model") as get_model,
        ):
            result = build_rag_pipeline(session).invoke({"question": "Unknown"})

        self.assertEqual(result["answer"], NO_CONTEXT_MESSAGE)
        self.assertEqual(result["documents"], [])
        retrieve.assert_called_once_with(session, "Unknown", top_k=5)
        get_model.assert_not_called()

    def test_rejects_empty_model_response(self) -> None:
        session = Mock(spec=Session)
        chunks = [retrieved_chunk("guide.txt", 0, "Context")]
        model = RunnableLambda(lambda _: AIMessage(content=" \n"))

        with (
            patch(
                "rag.langchain_retriever.retrieve_chunks", return_value=chunks
            ),
            patch("rag.langchain_pipeline._get_chat_model", return_value=model),
        ):
            with self.assertRaisesRegex(ValueError, "empty response"):
                build_rag_pipeline(session).invoke({"question": "Question"})

    def test_requires_api_key_when_creating_model(self) -> None:
        missing_key_config = ModuleType("config")
        missing_key_config.settings = SimpleNamespace(gemini_api_key=None)

        with patch.dict(sys.modules, {"config": missing_key_config}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                _get_chat_model()

    def test_configures_chat_model_with_secret_key(self) -> None:
        api_key = SecretStr("test-api-key")
        configured = ModuleType("config")
        configured.settings = SimpleNamespace(gemini_api_key=api_key)

        with (
            patch.dict(sys.modules, {"config": configured}),
            patch("rag.langchain_pipeline.ChatGoogleGenerativeAI") as chat_model,
        ):
            result = _get_chat_model()

        self.assertIs(result, chat_model.return_value)
        chat_model.assert_called_once_with(model=MODEL, api_key=api_key)

    def test_retrieval_failure_prevents_generation(self) -> None:
        session = Mock(spec=Session)

        with (
            patch(
                "rag.langchain_retriever.retrieve_chunks",
                side_effect=RuntimeError("retrieval failed"),
            ),
            patch("rag.langchain_pipeline._get_chat_model") as get_model,
        ):
            with self.assertRaisesRegex(RuntimeError, "retrieval failed"):
                build_rag_pipeline(session).invoke({"question": "Question"})

        get_model.assert_not_called()

    def test_generation_failure_propagates(self) -> None:
        session = Mock(spec=Session)
        chunks = [retrieved_chunk("guide.txt", 0, "Context")]

        def fail(_: object) -> AIMessage:
            raise RuntimeError("generation failed")

        model = RunnableLambda(fail)
        with (
            patch(
                "rag.langchain_retriever.retrieve_chunks", return_value=chunks
            ),
            patch("rag.langchain_pipeline._get_chat_model", return_value=model),
        ):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                build_rag_pipeline(session).invoke({"question": "Question"})


if __name__ == "__main__":
    unittest.main()
