"""Real QA/persistence against isolated SQLite; no provider/network calls."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from threading import Event
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://u:p@localhost/test")
sys.modules.setdefault("config", fake_config)

from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from auth import AuthenticatedUser, get_authenticated_user
from main import app
from rag.models import Conversation, Message
from rag.progress_router import ProgressQuestionRequest, stream_question
from rag.query_contract import QueryProcessingResult
from rag.retrieval import RetrievedChunk


@compiles(JSONB, "sqlite")
def sqlite_json(_type, compiler, **kw):
    return "JSON"


class QuestionProgressTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(temp.name) / 'isolated.db'}", connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine, "connect")
        def functions(connection, _record):
            connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
            connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat())
            connection.execute("PRAGMA foreign_keys=ON")
        Conversation.__table__.create(self.engine)
        Message.__table__.create(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.user = uuid4()
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(self.user)
        self.client = TestClient(app)
        def patched(target, **kwargs):
            patcher = patch(target, **kwargs)
            result = patcher.start(); self.addCleanup(patcher.stop)
            return result
        patched("rag.router.SessionLocal", new=self.sessions)
        self.query = patched("rag.qa.process_query", return_value=QueryProcessingResult("search", "Question", None, False, 1))
        self.chunk = RetrievedChunk(uuid4(), uuid4(), "fixture.txt", 0, "Evidence", .1)
        self.retrieval = patched("rag.langchain_retriever.retrieve_chunks", return_value=[self.chunk])
        self.answers = iter(["Validated answer [1]."])
        self.model = patched("rag.langchain_pipeline._get_chat_model", return_value=RunnableLambda(lambda _prompt: next(self.answers)))

    def payload(self, **changes):
        return {"question": "Question", "request_id": str(uuid4()), **changes}

    def stream(self, payload):
        response = self.client.post("/questions/stream", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        frames = []
        for frame in response.text.split("\n\n"):
            lines = frame.splitlines()
            if lines and lines[0].startswith("event:"):
                frames.append((lines[0].split(": ", 1)[1], json.loads(lines[1][6:])))
        self.assertTrue(all(data["request_id"] == payload["request_id"] for _, data in frames))
        return frames

    def count(self):
        with self.sessions() as session:
            return session.scalar(select(func.count(Message.id)))

    def test_success_real_stage_order_and_replay_without_duplicate_messages(self):
        payload = self.payload()
        frames = self.stream(payload)
        self.assertEqual([data["stage"] for name, data in frames if name == "progress"], ["query", "retrieval", "generation", "validation"])
        self.assertEqual(frames[-1][0], "result")
        self.assertEqual(frames[-1][1]["response"]["sources"][0]["chunk_id"], str(self.chunk.chunk_id))
        self.assertEqual(self.count(), 2)
        replay = self.stream(payload)
        self.assertEqual(replay[-1], frames[-1])
        self.assertEqual(self.count(), 2)
        self.query.assert_called_once()
        self.assertEqual(self.stream({**payload, "question": "Different"})[-1][1]["status"], 409)
        self.assertEqual(self.count(), 2)

    def test_request_validation_happens_before_qa_and_stream_has_proxy_headers(self):
        for payload in (
            {"question": "Question"},
            self.payload(request_id="invalid"),
            self.payload(question=" "),
            self.payload(top_k=0),
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/questions/stream", json=payload)
                self.assertEqual(response.status_code, 422)
        self.query.assert_not_called()
        self.assertEqual(self.count(), 0)
        response = self.client.post("/questions/stream", json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertEqual(self.count(), 2)

    def test_clarify_and_no_context_skip_unperformed_stages(self):
        self.query.return_value = QueryProcessingResult("clarify", None, "Which subject?", False, 1)
        frames = self.stream(self.payload())
        self.assertEqual([data["stage"] for name, data in frames if name == "progress"], ["query", "validation"])
        self.retrieval.assert_not_called(); self.model.assert_not_called()
        self.query.return_value = QueryProcessingResult("search", "Question", None, False, 1)
        self.retrieval.return_value = []
        frames = self.stream(self.payload())
        self.assertEqual([data["stage"] for name, data in frames if name == "progress"], ["query", "retrieval", "validation"])
        self.model.assert_not_called()
        self.assertEqual(self.count(), 4)

    def test_invalid_citations_provider_and_commit_failures_rollback_with_safe_error(self):
        for failure in ("citation", "provider", "commit"):
            with self.subTest(failure=failure):
                self.answers = iter(["Unverified [9]." if failure == "citation" else "Valid [1]."])
                if failure == "provider":
                    self.model.side_effect = RuntimeError("private secret")
                if failure == "commit":
                    with patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError("private secret")):
                        frames = self.stream(self.payload())
                else:
                    frames = self.stream(self.payload())
                self.model.side_effect = None
                self.assertEqual(frames[-1][0], "error")
                self.assertNotIn("private secret", json.dumps(frames))
                self.assertFalse(any(name == "result" for name, _ in frames))
                self.assertEqual(self.count(), 0)

    def test_auth_ownership_and_existing_conversation_persistence(self):
        payload = self.payload(conversation_id=str(uuid4()))
        self.assertEqual(self.stream(payload)[-1][1]["status"], 404)
        self.query.assert_not_called()
        first = self.stream(self.payload())[-1][1]["response"]
        self.answers = iter(["Follow-up [1]."])
        frames = self.stream(self.payload(conversation_id=first["conversation_id"]))
        self.assertEqual(frames[-1][1]["response"]["conversation_id"], first["conversation_id"])
        self.assertEqual(len(self.query.call_args.args[1]), 2)
        self.assertEqual(self.count(), 4)
        other = self.user
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(uuid4())
        self.assertEqual(self.stream(self.payload(conversation_id=first["conversation_id"]))[-1][1]["status"], 404)
        del app.dependency_overrides[get_authenticated_user]
        self.assertEqual(self.client.post("/questions/stream", json=self.payload()).status_code, 401)
        self.assertIsNotNone(other)

    def test_connection_close_during_provider_rolls_back_and_retry_reuses_request(self):
        entered, release, finished = Event(), Event(), Event()
        original_factory = self.sessions
        def factory():
            session = original_factory()
            close = session.close
            def tracked_close():
                close(); finished.set()
            session.close = tracked_close
            return session
        def model(_prompt):
            entered.set()
            release.wait(3)
            return "Answer [1]."
        self.model.return_value = RunnableLambda(model)
        payload = self.payload()
        async def run():
            response = await stream_question(ProgressQuestionRequest(**payload), AuthenticatedUser(self.user))
            iterator = response.body_iterator
            while not entered.is_set():
                await iterator.__anext__()
            await iterator.aclose()
            release.set()
            self.assertTrue(await asyncio.to_thread(finished.wait, 3))
        with patch("rag.router.SessionLocal", side_effect=factory):
            asyncio.run(run())
        self.assertEqual(self.count(), 0)
        self.model.return_value = RunnableLambda(lambda _: "Recovered [1].")
        self.assertEqual(self.stream(payload)[-1][0], "result")
        self.assertEqual(self.count(), 2)

    def test_concurrent_reconnects_serialize_and_commit_only_one_pair(self):
        from concurrent.futures import ThreadPoolExecutor
        entered, release = Event(), Event()
        def model(_prompt):
            entered.set()
            release.wait(3)
            return "One answer [1]."
        self.model.return_value = RunnableLambda(model)
        payload = self.payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.stream, payload)
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.stream, payload)
            release.set()
            self.assertEqual(first.result(timeout=5)[-1], second.result(timeout=5)[-1])
        self.query.assert_called_once()
        self.assertEqual(self.count(), 2)


if __name__ == "__main__":
    unittest.main()
