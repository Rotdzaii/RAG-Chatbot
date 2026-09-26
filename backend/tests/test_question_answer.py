import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_google_genai._common import GoogleGenerativeAIError
from sqlalchemy.exc import SQLAlchemyError


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user
from main import app
from rag.qa import QuestionAnswer
from rag.retrieval import RetrievedChunk


def retrieved_chunk(index: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="guide.txt",
        chunk_index=index,
        content=f"Reference {index}",
        cosine_distance=index / 10,
    )


class QuestionAnswerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=uuid4()
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_returns_answer_and_ordered_citations(self) -> None:
        session = Mock()
        sources = [retrieved_chunk(4), retrieved_chunk(7)]
        result = QuestionAnswer(answer="Answer [1]", sources=sources)

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", return_value=result) as answer_question,
        ):
            response = self.client.post(
                "/questions", json={"question": "  What is this?  ", "top_k": 2}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Answer [1]")
        self.assertEqual(
            response.json()["sources"],
            [
                {
                    "citation": 1,
                    "chunk_id": str(sources[0].chunk_id),
                    "document_id": str(sources[0].document_id),
                    "filename": "guide.txt",
                    "chunk_index": 4,
                    "cosine_distance": 0.4,
                },
                {
                    "citation": 2,
                    "chunk_id": str(sources[1].chunk_id),
                    "document_id": str(sources[1].document_id),
                    "filename": "guide.txt",
                    "chunk_index": 7,
                    "cosine_distance": 0.7,
                },
            ],
        )
        answer_question.assert_called_once_with(session, "What is this?", top_k=2)
        session.close.assert_called_once_with()

    def test_uses_default_top_k(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                return_value=QuestionAnswer(answer="No context", sources=[]),
            ) as answer_question,
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 200)
        answer_question.assert_called_once_with(session, "Question", top_k=5)
        session.close.assert_called_once_with()

    def test_rejects_blank_question_and_invalid_top_k_before_session_creation(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            blank_response = self.client.post("/questions", json={"question": " \n"})
            top_k_response = self.client.post(
                "/questions", json={"question": "Question", "top_k": 21}
            )

        self.assertEqual(blank_response.status_code, 422)
        self.assertEqual(top_k_response.status_code, 422)
        session_local.assert_not_called()

    def test_rejects_request_supplied_user_id_before_session_creation(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            response = self.client.post(
                "/questions",
                json={"question": "Question", "user_id": str(uuid4())},
            )

        self.assertEqual(response.status_code, 422)
        session_local.assert_not_called()

    def test_maps_rag_service_failures_to_generic_service_unavailable(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", side_effect=RuntimeError("internal")),
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Question answering is unavailable"}
        )
        session.close.assert_called_once_with()

    def test_maps_database_failures_to_generic_service_unavailable(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                side_effect=SQLAlchemyError("internal database detail"),
            ),
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Question answering is unavailable"}
        )
        session.close.assert_called_once_with()

    def test_maps_langchain_google_errors_to_generic_service_unavailable(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                side_effect=GoogleGenerativeAIError("internal provider detail"),
            ),
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Question answering is unavailable"}
        )
        session.close.assert_called_once_with()

    def test_propagates_unexpected_attribute_error_after_closing_session(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                side_effect=AttributeError("programming error"),
            ),
        ):
            with self.assertRaisesRegex(AttributeError, "programming error"):
                self.client.post("/questions", json={"question": "Question"})

        session.close.assert_called_once_with()


class QuestionAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_unauthenticated_request_is_rejected_before_rag_work(self) -> None:
        with (
            patch("rag.router.SessionLocal") as session_local,
            patch("rag.router.answer_question") as answer_question,
        ):
            response = self.client.post(
                "/questions", json={"question": "Question"}
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication required"})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        session_local.assert_not_called()
        answer_question.assert_not_called()

    def test_malformed_bearer_credentials_are_rejected_before_rag_work(self) -> None:
        malformed_headers = (
            {"Authorization": "Basic credentials"},
            {"Authorization": "Bearer"},
        )

        for headers in malformed_headers:
            with self.subTest(headers=headers):
                with (
                    patch("rag.router.SessionLocal") as session_local,
                    patch("rag.router.answer_question") as answer_question,
                ):
                    response = self.client.post(
                        "/questions",
                        json={"question": "Question"},
                        headers=headers,
                    )

                self.assertEqual(response.status_code, 401)
                session_local.assert_not_called()
                answer_question.assert_not_called()

if __name__ == "__main__":
    unittest.main()
