import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.generation import (
    MODEL,
    NO_CONTEXT_MESSAGE,
    SYSTEM_INSTRUCTION,
    _get_client,
    generate_answer,
)
from rag.retrieval import RetrievedChunk


def retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="guide.txt",
        chunk_index=3,
        content="Trusted reference content.",
        cosine_distance=0.1,
    )


class GenerateAnswerTests(unittest.TestCase):
    def test_rejects_blank_question_without_creating_client(self) -> None:
        with patch("rag.generation._get_client") as get_client:
            with self.assertRaisesRegex(ValueError, "Question must not be blank"):
                generate_answer(" \n", [retrieved_chunk()])

        get_client.assert_not_called()

    def test_returns_no_context_message_without_creating_client(self) -> None:
        with patch("rag.generation._get_client") as get_client:
            answer = generate_answer("Câu hỏi", [])

        self.assertEqual(answer, NO_CONTEXT_MESSAGE)
        get_client.assert_not_called()

    def test_generates_answer_with_numbered_context_and_closes_client(self) -> None:
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_text="  Câu trả lời [1]  "
        )

        with patch("rag.generation._get_client", return_value=client):
            answer = generate_answer("Câu hỏi?", [retrieved_chunk()])

        self.assertEqual(answer, "Câu trả lời [1]")
        client.interactions.create.assert_called_once()
        call = client.interactions.create.call_args
        self.assertEqual(call.kwargs["model"], MODEL)
        self.assertEqual(call.kwargs["system_instruction"], SYSTEM_INSTRUCTION)
        self.assertIn("[1]", call.kwargs["input"])
        self.assertIn("Filename: guide.txt", call.kwargs["input"])
        self.assertIn("Chunk index: 3", call.kwargs["input"])
        self.assertIn("Trusted reference content.", call.kwargs["input"])
        self.assertIn("Question:\nCâu hỏi?", call.kwargs["input"])
        client.close.assert_called_once_with()

    def test_rejects_empty_model_response_and_closes_client(self) -> None:
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(output_text=" \n")

        with patch("rag.generation._get_client", return_value=client):
            with self.assertRaisesRegex(ValueError, "empty response"):
                generate_answer("Question", [retrieved_chunk()])

        client.close.assert_called_once_with()

    def test_requires_api_key_when_creating_client(self) -> None:
        missing_key_config = ModuleType("config")
        missing_key_config.settings = SimpleNamespace(gemini_api_key=None)

        with patch.dict(sys.modules, {"config": missing_key_config}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                _get_client()


if __name__ == "__main__":
    unittest.main()
