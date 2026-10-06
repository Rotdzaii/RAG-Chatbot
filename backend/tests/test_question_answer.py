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
from rag.provider_errors import ProviderCallError
from rag.query_processing import HistoryMessage, QueryProcessingError
from rag.retrieval import RetrievedChunk


def retrieved_chunk(
    index: int,
    *,
    filename: str = "guide.txt",
    page_start: int | None = None,
    page_end: int | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename=filename,
        chunk_index=index,
        content=f"Reference {index}",
        cosine_distance=index / 10,
        page_start=page_start,
        page_end=page_end,
    )


class QuestionAnswerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        self.user_id = uuid4()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
            id=self.user_id
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_returns_answer_and_ordered_citations(self) -> None:
        session = Mock()
        sources = [
            retrieved_chunk(
                4,
                filename="single-page.pdf",
                page_start=3,
                page_end=3,
            ),
            retrieved_chunk(
                7,
                filename="page-range.pdf",
                page_start=8,
                page_end=10,
            ),
            retrieved_chunk(9),
        ]
        result = QuestionAnswer(answer="Answer [1] [2] [3]", sources=sources)

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", return_value=result) as answer_question,
        ):
            response = self.client.post(
                "/questions", json={"question": "  What is this?  ", "top_k": 3}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Answer [1] [2] [3]")
        self.assertIsNotNone(response.json()["conversation_id"])
        self.assertEqual(
            response.json()["sources"],
            [
                {
                    "citation": 1,
                    "chunk_id": str(sources[0].chunk_id),
                    "document_id": str(sources[0].document_id),
                    "filename": "single-page.pdf",
                    "chunk_index": 4,
                    "page_start": 3,
                    "page_end": 3,
                    "cosine_distance": 0.4,
                },
                {
                    "citation": 2,
                    "chunk_id": str(sources[1].chunk_id),
                    "document_id": str(sources[1].document_id),
                    "filename": "page-range.pdf",
                    "chunk_index": 7,
                    "page_start": 8,
                    "page_end": 10,
                    "cosine_distance": 0.7,
                },
                {
                    "citation": 3,
                    "chunk_id": str(sources[2].chunk_id),
                    "document_id": str(sources[2].document_id),
                    "filename": "guide.txt",
                    "chunk_index": 9,
                    "page_start": None,
                    "page_end": None,
                    "cosine_distance": 0.9,
                },
            ],
        )
        answer_question.assert_called_once_with(session, "What is this?", top_k=3)
        conversation = session.add.call_args.args[0]
        self.assertEqual(conversation.user_id, self.user_id)
        self.assertEqual(conversation.title, "What is this?")
        messages = session.add_all.call_args.args[0]
        self.assertEqual(len(messages), 2)
        self.assertEqual(
            [(message.role, message.content) for message in messages],
            [
                ("user", "What is this?"),
                ("assistant", "Answer [1] [2] [3]"),
            ],
        )
        self.assertIsNone(messages[0].citations)
        self.assertEqual(messages[1].citations, response.json()["sources"])
        self.assertEqual(
            response.json()["conversation_id"], str(conversation.id)
        )
        session.commit.assert_called_once_with()
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

    def test_returns_and_persists_only_cited_source_with_original_number(self) -> None:
        session = Mock()
        candidates = [retrieved_chunk(index) for index in (0, 1, 2)]
        result = QuestionAnswer(
            answer="Thông tin [2].",
            sources=candidates,
            cited_source_indices=(2,),
        )
        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", return_value=result),
        ):
            response = self.client.post("/questions", json={"question": "Thông tin?"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["sources"]), 1)
        self.assertEqual(response.json()["sources"][0]["citation"], 2)
        self.assertEqual(response.json()["sources"][0]["chunk_id"], str(candidates[1].chunk_id))
        messages = session.add_all.call_args.args[0]
        self.assertEqual(messages[1].citations, response.json()["sources"])

    def test_uncited_answer_does_not_return_candidate_sources(self) -> None:
        session = Mock()
        result = QuestionAnswer(
            answer="Không đủ căn cứ để trả lời.",
            sources=[retrieved_chunk(0)],
            cited_source_indices=(),
        )
        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", return_value=result),
        ):
            response = self.client.post("/questions", json={"question": "Câu hỏi?"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"], [])
        self.assertEqual(session.add_all.call_args.args[0][1].citations, [])

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
        session.rollback.assert_called_once_with()
        session.add.assert_not_called()
        session.add_all.assert_not_called()
        session.commit.assert_not_called()
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
        session.rollback.assert_called_once_with()
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
        session.rollback.assert_called_once_with()
        session.close.assert_called_once_with()

    def test_existing_conversation_requires_ownership_before_rag(self) -> None:
        session = Mock()
        conversation_id = uuid4()
        session.scalar.return_value = None

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.list_recent_owned_messages") as recent_history,
            patch("rag.router.answer_question") as answer_question,
        ):
            response = self.client.post(
                "/questions",
                json={
                    "question": "Question",
                    "conversation_id": str(conversation_id),
                },
            )

        self.assertEqual(response.status_code, 404)
        recent_history.assert_not_called()
        answer_question.assert_not_called()
        self.assertEqual(session.scalar.call_count, 1)
        session.rollback.assert_not_called()
        session.add.assert_not_called()
        session.add_all.assert_not_called()
        session.commit.assert_not_called()

    def test_success_appends_two_messages_to_owned_conversation(self) -> None:
        session = Mock()
        conversation_id = uuid4()
        conversation = SimpleNamespace(id=conversation_id, user_id=self.user_id)
        session.scalar.side_effect = [conversation, conversation]
        history = [
            HistoryMessage(role="user", content="Earlier question"),
            HistoryMessage(role="assistant", content="Earlier answer"),
        ]

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.list_recent_owned_messages",
                return_value=history,
            ) as recent_history,
            patch(
                "rag.router.answer_question",
                return_value=QuestionAnswer(answer="Answer", sources=[]),
            ) as answer_question,
        ):
            response = self.client.post(
                "/questions",
                json={
                    "question": "Follow up",
                    "conversation_id": str(conversation_id),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], str(conversation_id))
        recent_history.assert_called_once_with(
            session,
            conversation_id,
            self.user_id,
        )
        answer_question.assert_called_once_with(
            session,
            "Follow up",
            top_k=5,
            history=history,
        )
        session.add.assert_not_called()
        messages = session.add_all.call_args.args[0]
        self.assertEqual(len(messages), 2)
        self.assertTrue(
            all(message.conversation_id == conversation_id for message in messages)
        )
        session.commit.assert_called_once_with()

    def test_commit_failure_rolls_back_conversation_and_both_messages(self) -> None:
        session = Mock()
        session.commit.side_effect = SQLAlchemyError("write failed")

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                return_value=QuestionAnswer(answer="Answer", sources=[]),
            ),
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 503)
        session.add.assert_called_once()
        self.assertEqual(len(session.add_all.call_args.args[0]), 2)
        session.commit.assert_called_once_with()
        session.rollback.assert_called_once_with()

    def test_query_processing_failure_is_distinct_and_persists_nothing(self) -> None:
        session = Mock()

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                side_effect=QueryProcessingError("provider failed"),
            ),
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Question processing is unavailable"},
        )
        session.rollback.assert_called_once_with()
        session.add.assert_not_called()
        session.add_all.assert_not_called()
        session.commit.assert_not_called()

    def test_generation_provider_diagnostics_keep_generic_http_response(self) -> None:
        session = Mock()
        provider_error = ProviderCallError(
            error_stage="generation",
            cause_type="GoogleRateLimitError",
            provider_error_kind="rate_limit",
            provider_status_code=None,
            elapsed_ms=25.0,
        )

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch("rag.router.answer_question", side_effect=provider_error),
        ):
            response = self.client.post("/questions", json={"question": "Question"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Question answering is unavailable"},
        )
        self.assertNotIn("GoogleRateLimitError", response.text)
        session.rollback.assert_called_once_with()
        session.add.assert_not_called()
        session.add_all.assert_not_called()
        session.commit.assert_not_called()

    def test_clarification_is_saved_through_the_existing_message_flow(self) -> None:
        session = Mock()
        clarification = "Bạn đang muốn hỏi về ngành nào?"

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                return_value=QuestionAnswer(
                    answer=clarification,
                    sources=[],
                    query_processing_action="clarify",
                ),
            ),
        ):
            response = self.client.post(
                "/questions",
                json={"question": "Ngành này học bao lâu?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], clarification)
        self.assertEqual(response.json()["sources"], [])
        messages = session.add_all.call_args.args[0]
        self.assertEqual(
            [(message.role, message.content) for message in messages],
            [
                ("user", "Ngành này học bao lâu?"),
                ("assistant", clarification),
            ],
        )
        self.assertEqual(messages[1].citations, [])
        session.commit.assert_called_once_with()

    def test_clarification_persistence_failure_rolls_back_both_messages(self) -> None:
        session = Mock()
        session.commit.side_effect = SQLAlchemyError("write failed")

        with (
            patch("rag.router.SessionLocal", return_value=session),
            patch(
                "rag.router.answer_question",
                return_value=QuestionAnswer(
                    answer="Bạn đang muốn hỏi về ngành nào?",
                    sources=[],
                    query_processing_action="clarify",
                ),
            ),
        ):
            response = self.client.post(
                "/questions",
                json={"question": "Ngành này học bao lâu?"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(session.add_all.call_args.args[0]), 2)
        session.commit.assert_called_once_with()
        session.rollback.assert_called_once_with()

    def test_invalid_conversation_uuid_is_rejected_before_database_work(self) -> None:
        with patch("rag.router.SessionLocal") as session_local:
            response = self.client.post(
                "/questions",
                json={"question": "Question", "conversation_id": "not-a-uuid"},
            )

        self.assertEqual(response.status_code, 422)
        session_local.assert_not_called()

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
