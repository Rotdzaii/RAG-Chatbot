"""Check citation persistence directly; no HTTP server or provider is needed."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser  # noqa: E402
from rag.qa import QuestionAnswer  # noqa: E402
from rag.retrieval import RetrievedChunk  # noqa: E402
from rag.router import QuestionRequest, answer_question_request  # noqa: E402


class CitationRouterTests(unittest.TestCase):
    def test_invalid_generation_citation_does_not_persist_conversation(self) -> None:
        session = Mock()
        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", side_effect=ValueError("invalid citation")),
        ):
            with self.assertRaises(HTTPException) as raised:
                answer_question_request(
                    QuestionRequest(question="Một câu hỏi?"), AuthenticatedUser(id=uuid4())
                )
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Question answering is unavailable")
        session.add_all.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_called_once_with()

    def test_original_reference_number_survives_http_and_persistence(self) -> None:
        session = Mock()
        candidates = [
            RetrievedChunk(
                chunk_id=uuid4(), document_id=uuid4(), filename="source.pdf",
                chunk_index=index, content="text", cosine_distance=0.1,
            ) for index in range(3)
        ]
        result = QuestionAnswer(
            answer="Một thông tin [2].", sources=candidates, cited_source_indices=(2,)
        )
        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", return_value=result),
        ):
            response = answer_question_request(
                QuestionRequest(question="Một câu hỏi?"), AuthenticatedUser(id=uuid4())
            )

        self.assertEqual(len(response.sources), 1)
        self.assertEqual(response.sources[0].citation, 2)
        self.assertEqual(response.sources[0].chunk_id, candidates[1].chunk_id)
        self.assertEqual(session.add_all.call_args.args[0][1].citations[0]["citation"], 2)
        session.commit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
