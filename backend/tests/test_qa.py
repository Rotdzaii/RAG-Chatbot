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

from rag.qa import QuestionAnswer, answer_question
from rag.retrieval import RetrievedChunk


def retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="guide.txt",
        chunk_index=0,
        content="Reference content.",
        cosine_distance=0.1,
    )


class AnswerQuestionTests(unittest.TestCase):
    def test_returns_generated_answer_and_sources_in_retrieval_order(self) -> None:
        session = Mock()
        chunks = [retrieved_chunk(), retrieved_chunk()]

        with (
            patch("rag.qa.retrieve_chunks", return_value=chunks) as retrieve,
            patch("rag.qa.generate_answer", return_value="Answer [1]") as generate,
        ):
            result = answer_question(session, "What is this?", top_k=2)

        self.assertEqual(result, QuestionAnswer(answer="Answer [1]", sources=chunks))
        self.assertIs(result.sources, chunks)
        retrieve.assert_called_once_with(session, "What is this?", top_k=2)
        generate.assert_called_once_with("What is this?", chunks)

    def test_passes_empty_retrieval_results_to_generation(self) -> None:
        session = Mock()

        with (
            patch("rag.qa.retrieve_chunks", return_value=[]) as retrieve,
            patch("rag.qa.generate_answer", return_value="Không có ngữ cảnh.") as generate,
        ):
            result = answer_question(session, "Câu hỏi")

        self.assertEqual(result.sources, [])
        self.assertEqual(result.answer, "Không có ngữ cảnh.")
        retrieve.assert_called_once_with(session, "Câu hỏi", top_k=5)
        generate.assert_called_once_with("Câu hỏi", [])

    def test_propagates_retrieval_failure_without_generation(self) -> None:
        session = Mock()

        with (
            patch("rag.qa.retrieve_chunks", side_effect=ValueError("invalid query")),
            patch("rag.qa.generate_answer") as generate,
        ):
            with self.assertRaisesRegex(ValueError, "invalid query"):
                answer_question(session, "question")

        generate.assert_not_called()

    def test_propagates_generation_failure(self) -> None:
        session = Mock()
        chunks = [retrieved_chunk()]

        with (
            patch("rag.qa.retrieve_chunks", return_value=chunks),
            patch("rag.qa.generate_answer", side_effect=RuntimeError("unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                answer_question(session, "question")


if __name__ == "__main__":
    unittest.main()
