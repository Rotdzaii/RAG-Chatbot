import sys
import unittest
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user  # noqa: E402
from main import app  # noqa: E402
from rag.conversations import (  # noqa: E402
    AUTO_TITLE_MAX_LENGTH,
    HISTORY_MAX_MESSAGES,
    create_title_from_question,
    delete_owned_conversation,
    get_owned_conversation,
    list_owned_conversations,
    list_owned_messages,
    list_recent_owned_messages,
    update_owned_conversation,
)


def conversation_record(*, user_id=None, title="Conversation", is_pinned=False):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        title=title,
        is_pinned=is_pinned,
        created_at=now,
        updated_at=now,
    )


class ConversationQueryTests(unittest.TestCase):
    def test_generated_title_normalizes_whitespace_without_using_an_llm(self) -> None:
        question = "  A   question\nwith\tspacing " + ("x" * 100)

        title = create_title_from_question(question)

        self.assertLessEqual(len(title), AUTO_TITLE_MAX_LENGTH)
        self.assertNotIn("\n", title)
        self.assertNotIn("\t", title)
        self.assertTrue(title.endswith("…"))

    def test_list_is_owned_and_sorted_pinned_then_recent(self) -> None:
        session = Mock(spec=Session)
        session.scalars.return_value = []
        user_id = uuid4()

        self.assertEqual(list_owned_conversations(session, user_id), [])

        statement = session.scalars.call_args.args[0]
        sql = str(statement)
        self.assertIn("conversations.user_id =", sql)
        self.assertIn(
            "ORDER BY conversations.is_pinned DESC, conversations.updated_at DESC",
            sql,
        )
        self.assertIn(user_id, statement.compile().params.values())

    def test_owned_conversation_query_filters_id_and_user(self) -> None:
        session = Mock(spec=Session)
        session.scalar.return_value = None
        conversation_id = uuid4()
        user_id = uuid4()

        get_owned_conversation(session, conversation_id, user_id)

        statement = session.scalar.call_args.args[0]
        sql = str(statement)
        self.assertIn("conversations.id =", sql)
        self.assertIn("conversations.user_id =", sql)
        self.assertIn(conversation_id, statement.compile().params.values())
        self.assertIn(user_id, statement.compile().params.values())

    def test_message_query_rechecks_owner_and_orders_oldest_first(self) -> None:
        session = Mock(spec=Session)
        session.scalar.return_value = conversation_record()
        session.scalars.return_value = []
        conversation_id = uuid4()
        user_id = uuid4()

        self.assertEqual(
            list_owned_messages(session, conversation_id, user_id), []
        )

        statement = session.scalars.call_args.args[0]
        sql = str(statement)
        self.assertIn("JOIN conversations", sql)
        self.assertIn("conversations.user_id =", sql)
        self.assertIn("ORDER BY messages.created_at ASC", sql)

    def test_recent_history_is_owned_limited_ordered_and_bounded(self) -> None:
        session = Mock(spec=Session)
        conversation_id = uuid4()
        user_id = uuid4()
        chronological = [
            SimpleNamespace(
                role="user" if index % 2 == 0 else "assistant",
                content=f"message-{index}",
            )
            for index in range(14)
        ]
        session.scalars.return_value = list(reversed(chronological))

        history = list_recent_owned_messages(
            session,
            conversation_id,
            user_id,
        )

        self.assertEqual(HISTORY_MAX_MESSAGES, 12)
        self.assertEqual(
            [message.content for message in history],
            [f"message-{index}" for index in range(2, 14)],
        )
        statement = session.scalars.call_args.args[0]
        sql = str(statement)
        self.assertIn("JOIN conversations", sql)
        self.assertIn("conversations.user_id =", sql)
        self.assertIn("ORDER BY messages.created_at DESC", sql)
        self.assertEqual(statement._limit_clause.value, HISTORY_MAX_MESSAGES)
        self.assertIn(conversation_id, statement.compile().params.values())
        self.assertIn(user_id, statement.compile().params.values())

        session.scalars.return_value = [
            SimpleNamespace(role="assistant", content="newest"),
            SimpleNamespace(role="user", content="older-value"),
        ]
        bounded = list_recent_owned_messages(
            session,
            conversation_id,
            user_id,
            max_characters=10,
        )
        self.assertEqual(
            [message.role for message in bounded],
            ["user", "assistant"],
        )
        self.assertLessEqual(sum(len(message.content) for message in bounded), 10)

    def test_update_and_delete_statements_include_owner_filter(self) -> None:
        session = Mock(spec=Session)
        session.scalar.return_value = None
        conversation_id = uuid4()
        user_id = uuid4()
        now = datetime.now(timezone.utc)

        update_owned_conversation(
            session,
            conversation_id,
            user_id,
            title="Updated",
            updated_at=now,
        )
        update_statement = session.scalar.call_args.args[0]
        self.assertIn("conversations.user_id =", str(update_statement))

        delete_owned_conversation(session, conversation_id, user_id)
        delete_statement = session.scalar.call_args.args[0]
        self.assertIn("conversations.user_id =", str(delete_statement))


class ConversationApiTests(unittest.TestCase):
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

    def test_lists_only_current_users_conversations(self) -> None:
        session = Mock()
        own = conversation_record(user_id=self.user_id, title="Own")

        with (
            patch("rag.conversation_router.SessionLocal", return_value=session),
            patch(
                "rag.conversation_router.list_owned_conversations",
                return_value=[own],
            ) as list_owned,
        ):
            response = self.client.get("/conversations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["title"] for item in response.json()], ["Own"])
        list_owned.assert_called_once_with(session, self.user_id)
        session.close.assert_called_once_with()

    def test_create_assigns_authenticated_user_and_rejects_client_user_id(self) -> None:
        session = Mock()

        with patch("rag.conversation_router.SessionLocal", return_value=session):
            response = self.client.post(
                "/conversations", json={"title": "  New conversation  "}
            )

        self.assertEqual(response.status_code, 201)
        created = session.add.call_args.args[0]
        self.assertEqual(created.user_id, self.user_id)
        self.assertEqual(created.title, "New conversation")
        self.assertFalse(created.is_pinned)
        session.commit.assert_called_once_with()

        with patch("rag.conversation_router.SessionLocal") as session_local:
            rejected = self.client.post(
                "/conversations",
                json={"title": "Attempt", "user_id": str(uuid4())},
            )

        self.assertEqual(rejected.status_code, 422)
        session_local.assert_not_called()

    def test_other_users_messages_are_hidden_as_not_found(self) -> None:
        session = Mock()
        conversation_id = uuid4()

        with (
            patch("rag.conversation_router.SessionLocal", return_value=session),
            patch(
                "rag.conversation_router.list_owned_messages", return_value=None
            ) as list_messages,
        ):
            response = self.client.get(
                f"/conversations/{conversation_id}/messages"
            )

        self.assertEqual(response.status_code, 404)
        list_messages.assert_called_once_with(
            session, conversation_id, self.user_id
        )

    def test_other_users_conversation_cannot_be_renamed_or_pinned(self) -> None:
        conversation_id = uuid4()

        for payload in ({"title": "Renamed"}, {"is_pinned": True}):
            with self.subTest(payload=payload):
                session = Mock()
                with (
                    patch(
                        "rag.conversation_router.SessionLocal",
                        return_value=session,
                    ),
                    patch(
                        "rag.conversation_router.update_owned_conversation",
                        return_value=None,
                    ) as update_owned,
                ):
                    response = self.client.patch(
                        f"/conversations/{conversation_id}", json=payload
                    )

                self.assertEqual(response.status_code, 404)
                self.assertEqual(
                    update_owned.call_args.args[:3],
                    (session, conversation_id, self.user_id),
                )
                session.commit.assert_not_called()

    def test_other_users_conversation_cannot_be_deleted(self) -> None:
        session = Mock()
        conversation_id = uuid4()

        with (
            patch("rag.conversation_router.SessionLocal", return_value=session),
            patch(
                "rag.conversation_router.delete_owned_conversation",
                return_value=False,
            ) as delete_owned,
        ):
            response = self.client.delete(f"/conversations/{conversation_id}")

        self.assertEqual(response.status_code, 404)
        delete_owned.assert_called_once_with(
            session, conversation_id, self.user_id
        )
        session.commit.assert_not_called()

    def test_invalid_uuid_is_rejected_before_session_creation(self) -> None:
        with patch("rag.conversation_router.SessionLocal") as session_local:
            response = self.client.get("/conversations/not-a-uuid/messages")

        self.assertEqual(response.status_code, 422)
        session_local.assert_not_called()


class ConversationAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_unauthenticated_request_is_rejected_before_database_work(self) -> None:
        with patch("rag.conversation_router.SessionLocal") as session_local:
            response = self.client.get("/conversations")

        self.assertEqual(response.status_code, 401)
        session_local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
