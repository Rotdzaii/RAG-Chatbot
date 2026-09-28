import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from langchain_core.documents import Document


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.qa import QuestionAnswer, answer_question  # noqa: E402


def source_document(filename: str, index: int, content: str) -> Document:
    return Document(
        page_content=content,
        metadata={
            "chunk_id": str(uuid4()),
            "document_id": str(uuid4()),
            "filename": filename,
            "chunk_index": index,
            "cosine_distance": 0.1 + index / 100,
        },
    )


class AnswerQuestionTests(unittest.TestCase):
    def test_returns_answer_and_typed_sources_in_pipeline_order(self) -> None:
        session = Mock()
        documents = [
            source_document("first.txt", 1, "First source."),
            source_document("second.pdf", 2, "Second source."),
        ]
        pipeline = Mock()
        pipeline.invoke.return_value = {
            "answer": "Answer [1] [2]",
            "documents": documents,
        }

        with patch("rag.qa.build_rag_pipeline", return_value=pipeline) as build:
            result = answer_question(session, "What is this?", top_k=2)

        self.assertIsInstance(result, QuestionAnswer)
        self.assertEqual(result.answer, "Answer [1] [2]")
        self.assertEqual(
            [source.filename for source in result.sources],
            ["first.txt", "second.pdf"],
        )
        self.assertEqual(
            [source.content for source in result.sources],
            ["First source.", "Second source."],
        )
        self.assertEqual(
            [source.chunk_index for source in result.sources], [1, 2]
        )
        self.assertTrue(
            all(isinstance(source.chunk_id, UUID) for source in result.sources)
        )
        self.assertTrue(
            all(isinstance(source.document_id, UUID) for source in result.sources)
        )
        self.assertTrue(
            all(isinstance(source.cosine_distance, float) for source in result.sources)
        )
        build.assert_called_once_with(session, top_k=2)
        pipeline.invoke.assert_called_once_with({"question": "What is this?"})

    def test_returns_empty_sources_from_no_context_result(self) -> None:
        session = Mock()
        pipeline = Mock()
        pipeline.invoke.return_value = {
            "answer": "Không có ngữ cảnh phù hợp để trả lời câu hỏi này.",
            "documents": [],
        }

        with patch("rag.qa.build_rag_pipeline", return_value=pipeline) as build:
            result = answer_question(session, "Câu hỏi")

        self.assertEqual(result.sources, [])
        self.assertEqual(
            result.answer, "Không có ngữ cảnh phù hợp để trả lời câu hỏi này."
        )
        build.assert_called_once_with(session, top_k=5)
        pipeline.invoke.assert_called_once_with({"question": "Câu hỏi"})

    def test_propagates_pipeline_failure(self) -> None:
        session = Mock()
        pipeline = Mock()
        pipeline.invoke.side_effect = RuntimeError("pipeline failed")

        with patch("rag.qa.build_rag_pipeline", return_value=pipeline):
            with self.assertRaisesRegex(RuntimeError, "pipeline failed"):
                answer_question(session, "question")

        pipeline.invoke.assert_called_once_with({"question": "question"})


if __name__ == "__main__":
    unittest.main()
