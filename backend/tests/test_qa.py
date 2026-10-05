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
from rag.query_processing import (  # noqa: E402
    HistoryMessage,
    QueryProcessingResult,
)


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


def search_result(
    question: str,
    *,
    history_used: bool = False,
) -> QueryProcessingResult:
    return QueryProcessingResult(
        action="search",
        standalone_query=question,
        clarification=None,
        history_used=history_used,
        elapsed_ms=4.5,
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

        with (
            patch(
                "rag.qa.process_query",
                return_value=search_result("What is this?"),
            ) as process,
            patch("rag.qa.build_rag_pipeline", return_value=pipeline) as build,
        ):
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
        process.assert_called_once_with("What is this?", ())
        pipeline.invoke.assert_called_once_with({"question": "What is this?"})
        self.assertEqual(result.query_processing_action, "search")
        self.assertFalse(result.history_used)
        self.assertEqual(result.query_processing_elapsed_ms, 4.5)

    def test_returns_empty_sources_from_no_context_result(self) -> None:
        session = Mock()
        pipeline = Mock()
        pipeline.invoke.return_value = {
            "answer": "Không có ngữ cảnh phù hợp để trả lời câu hỏi này.",
            "documents": [],
        }

        with (
            patch(
                "rag.qa.process_query",
                return_value=search_result("Câu hỏi"),
            ),
            patch("rag.qa.build_rag_pipeline", return_value=pipeline) as build,
        ):
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

        with (
            patch(
                "rag.qa.process_query",
                return_value=search_result("question"),
            ),
            patch("rag.qa.build_rag_pipeline", return_value=pipeline),
        ):
            with self.assertRaisesRegex(RuntimeError, "pipeline failed"):
                answer_question(session, "question")

        pipeline.invoke.assert_called_once_with({"question": "question"})

    def test_follow_up_uses_resolved_query_without_passing_history_as_evidence(
        self,
    ) -> None:
        session = Mock()
        history = [
            HistoryMessage(role="user", content="Ngành Marketing có gì?"),
            HistoryMessage(role="assistant", content="Một câu trả lời cũ."),
        ]
        pipeline = Mock()
        pipeline.invoke.return_value = {"answer": "3,5 năm [1]", "documents": []}

        with (
            patch(
                "rag.qa.process_query",
                return_value=search_result(
                    "Thời gian đào tạo ngành Marketing là bao lâu?",
                    history_used=True,
                ),
            ) as process,
            patch("rag.qa.build_rag_pipeline", return_value=pipeline),
        ):
            result = answer_question(
                session,
                "Ngành đó học bao lâu?",
                history=history,
            )

        process.assert_called_once_with("Ngành đó học bao lâu?", history)
        pipeline.invoke.assert_called_once_with(
            {"question": "Thời gian đào tạo ngành Marketing là bao lâu?"}
        )
        self.assertNotIn(
            "Một câu trả lời cũ.",
            str(pipeline.invoke.call_args.args[0]),
        )
        self.assertTrue(result.history_used)
        self.assertEqual(
            result.rewritten_query,
            "Thời gian đào tạo ngành Marketing là bao lâu?",
        )

    def test_clarification_skips_retrieval_and_generation(self) -> None:
        session = Mock()

        with (
            patch(
                "rag.qa.process_query",
                return_value=QueryProcessingResult(
                    action="clarify",
                    standalone_query=None,
                    clarification="Bạn đang hỏi về ngành nào?",
                    history_used=False,
                    elapsed_ms=3.0,
                ),
            ),
            patch("rag.qa.build_rag_pipeline") as build,
        ):
            result = answer_question(session, "Ngành này học bao lâu?")

        self.assertEqual(result.answer, "Bạn đang hỏi về ngành nào?")
        self.assertEqual(result.sources, [])
        self.assertEqual(result.query_processing_action, "clarify")
        self.assertIsNone(result.rewritten_query)
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
