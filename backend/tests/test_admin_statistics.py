"""Offline operational telemetry, deduplication, time bounds and admin reports."""

from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import test_source_activation as fixture
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from rag.langchain_pipeline import GroundedAnswer
from auth import AuthenticatedUser, get_authenticated_user
from devtools import admin_statistics_preview
from rag.admin_statistics import ADMIN_TIMEZONE, _citation_pairs
from answer_fixture import GroundedModelStub
from rag.models import Chunk, Conversation, Document, Message, QuestionTurn
from rag.question_outcomes import Outcome, QuestionExecution, Resolution, combine_resolutions
from rag.question_tracking import QuestionAttempt, finish_rolled_back_turn


class OutcomeTests(unittest.TestCase):
    def test_multipart_precedence_and_unioned_reasons(self):
        cases = (
            ([Outcome.ANSWERED, Outcome.ANSWERED], Outcome.ANSWERED),
            ([Outcome.ANSWERED, Outcome.ERROR], Outcome.PARTIAL),
            ([Outcome.PARTIAL, Outcome.CLARIFY], Outcome.PARTIAL),
            ([Outcome.INSUFFICIENT, Outcome.UNAVAILABLE], Outcome.UNAVAILABLE),
            ([Outcome.ERROR, Outcome.CLARIFY], Outcome.ERROR),
            ([Outcome.CLARIFY, Outcome.INSUFFICIENT], Outcome.CLARIFY),
            ([Outcome.INSUFFICIENT, Outcome.INSUFFICIENT], Outcome.INSUFFICIENT),
        )
        for parts, expected in cases:
            with self.subTest(parts=parts):
                merged = combine_resolutions([Resolution(part, (part.value,)) for part in parts])
                self.assertEqual(merged.outcome, expected)
                self.assertEqual(merged.reasons, tuple(sorted(set(parts))))

    def test_migration_is_a_single_head_and_compiles_offline_for_postgresql(self):
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        graph = ScriptDirectory(str(migrations))
        self.assertEqual(graph.get_heads(), ["8d9636d1c45e"])
        self.assertEqual(graph.get_revision("8d9636d1c45e").down_revision, "a7e3c9d1b502")
        revision = runpy.run_path(str(migrations / "versions/8d9636d1c45e_add_question_turns.py"))
        rendered = StringIO()
        migration = MigrationContext.configure(dialect_name="postgresql", opts={
            "as_sql": True, "output_buffer": rendered,
        })
        with Operations.context(migration):
            revision["upgrade"]()
            revision["downgrade"]()
        ddl = rendered.getvalue()
        self.assertIn("CREATE TABLE question_turns", ddl)
        self.assertIn("FOREIGN KEY(assistant_message_id) REFERENCES messages (id) ON DELETE SET NULL", ddl)
        self.assertIn("ALTER TABLE question_turns ENABLE ROW LEVEL SECURITY", ddl)
        self.assertIn("DROP TABLE question_turns", ddl)

    def test_postgresql_ranking_expands_jsonb_with_explicit_provenance(self):
        dialect = postgresql.dialect()
        session = Mock()
        session.get_bind.return_value.dialect = dialect
        start = datetime(2026, 11, 18, tzinfo=timezone.utc)
        end = datetime(2026, 11, 19, tzinfo=timezone.utc)
        citation_pairs = _citation_pairs(session, start, end)
        sql = str(select(citation_pairs).compile(dialect=dialect))
        self.assertIn("jsonb_array_elements", sql)
        self.assertIn("question_turns.citation_version =", sql)
        self.assertIn("GROUP BY messages.id, messages.created_at", sql)


class AdminStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.db = fixture.SourceActivationTests()
        self.db.setUp()
        self.addCleanup(self.db.doCleanups)
        p = patch("rag.admin_statistics.SessionLocal", self.db.sessions)
        p.start()
        self.addCleanup(p.stop)

    def preview_client(self):
        preview = admin_statistics_preview.app
        auth = patch.dict(preview.dependency_overrides, self.db.client.app.dependency_overrides)
        auth.start()
        self.addCleanup(auth.stop)
        admin_statistics_preview._load_preview.cache_clear()
        self.addCleanup(admin_statistics_preview._load_preview.cache_clear)
        return TestClient(preview)

    def ask(self, identifier=None, question="Câu hỏi riêng tư"):
        payload = {"question": question}
        if identifier is not None:
            payload["request_id"] = str(identifier)
        return self.db.client.post("/questions", json=payload)

    def row(self, request_id):
        with self.db.sessions() as session:
            return session.get(QuestionTurn, (self.db.admin, request_id))

    def document(self):
        with self.db.sessions() as session:
            session.add(Document(
                filename="private.pdf", mime_type="application/pdf", is_active=True,
                chunks=[Chunk(chunk_index=0, content="private chunk", embedding=[1.] + [0.] * 767)],
            ))
            session.commit()

    def test_failed_retry_fingerprint_cross_transport_replay_and_deletion(self):
        request_id = uuid4()
        self.document()
        with patch("rag.langchain_retriever.retrieve_chunks", side_effect=RuntimeError("private exception")):
            failed = self.ask(request_id)
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("private exception", failed.text)
        original = self.row(request_id)
        self.assertEqual((original.state, original.outcome, original.assistant_message_id), ("failed", "error", None))
        self.assertEqual(original.executed_routes, ["internal"])
        with self.db.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Message)), 0)
        self.assertEqual(self.ask(request_id, question="changed payload").status_code, 409)
        self.assertEqual(self.row(request_id).attempt_id, original.attempt_id)

        self.db.model.return_value = GroundedModelStub(
            lambda _: GroundedAnswer(outcome="partial", answer="Phần đủ dữ kiện [1].")
        )
        response = self.ask(request_id)
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.row(request_id)
        self.assertEqual(saved.received_at, original.received_at)
        self.assertEqual((saved.state, saved.outcome, saved.citation_version), ("completed", "partial", 1))
        self.assertIsNotNone(saved.assistant_message_id)
        with patch("rag.router.answer_question", side_effect=RuntimeError("must not run")) as answer:
            replay = self.db.client.post("/questions/stream", json={
                "question": "Câu hỏi riêng tư", "request_id": str(request_id),
            })
            frames = [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")]
            self.assertEqual(frames[-1]["response"], response.json())
            answer.assert_not_called()
        self.assertEqual(self.row(request_id).attempt_id, saved.attempt_id)
        self.assertEqual(self.ask(request_id, question="changed payload").status_code, 409)
        with self.db.sessions() as session:
            finish_rolled_back_turn(
                session, QuestionAttempt(self.db.admin, request_id, saved.attempt_id), QuestionExecution(),
                failure_reason="unexpected_error",
            )
            self.assertEqual(session.scalar(select(func.count()).select_from(QuestionTurn)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Message)), 2)
        self.assertEqual((self.row(request_id).state, self.row(request_id).outcome), ("completed", "partial"))
        removed = self.db.client.delete(f"/conversations/{response.json()['conversation_id']}")
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(self.row(request_id).state, "completed")
        self.assertIsNone(self.row(request_id).assistant_message_id)
        self.assertEqual(self.ask(request_id).status_code, 410)

    def test_commit_rollback_records_failure_and_telemetry_failure_preserves_primary_result(self):
        request_id, failed_stats_id = uuid4(), uuid4()
        original_commit = self.db.sessions.class_.commit

        def commit_failure(session):
            if type(session) is self.db.sessions.class_:
                raise SQLAlchemyError("primary write failed")
            return original_commit(session)

        with patch.object(self.db.sessions.class_, "commit", commit_failure):
            response = self.ask(request_id)
        self.assertEqual(response.status_code, 503, response.text)
        failed = self.row(request_id)
        self.assertEqual((failed.state, failed.outcome, failed.reasons), ("failed", "error", ["database_error"]))
        with self.db.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Message)), 0)

        with patch("rag.question_tracking._finish", side_effect=SQLAlchemyError("telemetry private")):
            success = self.ask(failed_stats_id)
            self.assertEqual(success.status_code, 200, success.text)
            retry = self.ask(failed_stats_id)
            self.assertEqual(retry.json(), success.json())
            with patch("rag.router.answer_question", side_effect=RuntimeError("primary processing failed")):
                original_error = self.ask(uuid4())
                self.assertEqual(original_error.status_code, 503)
                self.assertEqual(original_error.json()["detail"], "Question answering is unavailable")
        self.assertEqual(self.row(failed_stats_id).state, "running")
        with self.db.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Message)), 2)

    def test_http_without_request_id_counts_each_call(self):
        self.assertEqual(self.ask().status_code, 200)
        self.assertEqual(self.ask().status_code, 200)
        with self.db.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(QuestionTurn)), 2)

    def test_preview_reads_attached_data_by_local_date_without_using_database(self):
        client = self.preview_client()
        end = "&to=2026-11-20"
        with (
            patch("rag.admin_statistics.SessionLocal", side_effect=AssertionError("preview must not open a session")),
            patch("devtools.admin_statistics_preview.datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = datetime(2026, 11, 19, 0, 30, tzinfo=ADMIN_TIMEZONE)
            response = client.get("/admin/statistics?from=2026-10-21" + end)
            self.assertEqual(response.status_code, 200, response.text)
            full = response.json()
            self.assertEqual(full["outcome_denominator"], 128)
            self.assertEqual(full["by_outcome"]["answered"], {"count": 102, "ratio": 102 / 128})
            self.assertEqual(full["by_executed_route"]["internal"], {"count": 105, "ratio": 105 / 128})
            self.assertEqual(full["data_started_at"], "2026-10-20T17:00:00Z")
            self.assertEqual(len(full["ranked_documents"]), 3)
            self.assertEqual(len(full["daily_classified"]), 30)
            self.assertEqual(sum(day["count"] for day in full["daily_classified"]), 128)
            self.assertEqual(full["daily_classified"][0], {"date": "2026-10-21", "count": 4})

            recent = client.get("/admin/statistics?from=2026-11-13" + end).json()
            self.assertEqual(recent["outcome_denominator"], 32)
            self.assertEqual(recent["by_outcome"]["answered"], {"count": 26, "ratio": 26 / 32})
            self.assertEqual(recent["by_outcome"]["partial"], {"count": 3, "ratio": 3 / 32})
            self.assertEqual(sum(day["count"] for day in recent["daily_classified"]), 32)
            limited = client.get("/admin/statistics?from=2026-10-21" + end + "&limit=1").json()
            self.assertEqual(limited["ranked_documents"], full["ranked_documents"][:1])
            self.assertEqual(limited["cited_answer_denominator"], full["cited_answer_denominator"])

            first_day = client.get("/admin/statistics?from=2026-10-20&to=2026-10-22").json()
            self.assertEqual(first_day["outcome_denominator"], 4)
            self.assertEqual(first_day["cited_answer_denominator"], 4)
            self.assertEqual(
                {row["filename"]: row["ratio"] for row in first_day["ranked_documents"]},
                {
                    "marketing_vlu_web_2026-10-01.pdf": 0.5,
                    "mang-may-tinh-va-truyen-thong-du-lieu.html": 0.25,
                    "software_engineering_vlu_web_2026-10-06.pdf": 0.5,
                },
            )
            for bounds in ("from=2026-10-20&to=2026-10-21", "from=2026-11-20&to=2026-11-21"):
                empty = client.get("/admin/statistics?" + bounds).json()
                self.assertEqual(empty["outcome_denominator"], 0)
                self.assertEqual(empty["by_outcome"]["answered"], {"count": None, "ratio": None})
                self.assertEqual(empty["ranked_documents"], [])
                self.assertIsNone(empty["daily_classified"][0]["count"])
            maximum = client.get("/admin/statistics?from=2026-10-20&to=2026-11-20")
            self.assertEqual(maximum.status_code, 200, maximum.text)
            self.assertEqual(len(maximum.json()["daily_classified"]), 31)
            self.assertEqual(maximum.json()["daily_classified"][0], {"date": "2026-10-20", "count": None})
            clock.now.return_value = datetime(2026, 11, 20, 0, 1, tzinfo=ADMIN_TIMEZONE)
            following_day = client.get("/admin/statistics?from=2026-11-14&to=2026-11-21").json()
            self.assertEqual(following_day["by_outcome"], recent["by_outcome"])
            self.assertEqual(following_day["data_started_at"], "2026-10-21T17:00:00Z")
            clock.now.assert_called_with(ADMIN_TIMEZONE)

        database = self.db.client.get("/admin/statistics?from=2026-10-21" + end)
        self.assertEqual(database.status_code, 200, database.text)
        self.assertIsNone(database.json()["data_started_at"])
        self.assertEqual(database.json()["outcome_denominator"], 0)

    def test_preview_keeps_admin_guard_and_reports_invalid_fixture_without_falling_back(self):
        client = self.preview_client()
        url = "/admin/statistics?from=2026-11-13&to=2026-11-20"
        with (
            patch("rag.admin_statistics.SessionLocal", side_effect=AssertionError("preview must not open a session")),
            patch("devtools.admin_statistics_preview.PREVIEW_FILE") as file,
        ):
            with patch.dict(client.app.dependency_overrides, {
                get_authenticated_user: lambda: AuthenticatedUser(uuid4()),
            }):
                self.assertEqual(client.get(url).status_code, 403)
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            file.read_text.assert_not_called()

            invalid_range = client.get("/admin/statistics?from=2026-11-20&to=2026-11-20")
            self.assertEqual(invalid_range.status_code, 422)
            too_long = client.get("/admin/statistics?from=2026-10-19&to=2026-11-20")
            self.assertEqual(too_long.status_code, 422)
            file.read_text.assert_not_called()
            file.read_text.side_effect = FileNotFoundError("private absolute path")
            missing = client.get(url)
            self.assertEqual(missing.status_code, 503)
            self.assertNotIn("private absolute path", missing.text)
            file.read_text.side_effect = None
            file.read_text.return_value = '{"days":[]}'
            invalid = client.get(url)
            self.assertEqual(invalid.status_code, 503)
            self.assertEqual(invalid.json(), missing.json())

    def test_aggregation_deduplicates_citations_tracks_lifecycle_and_uses_local_day(self):
        document_id, gone = uuid4(), uuid4()
        conversation_id = uuid4()
        at_start = datetime(2026, 11, 18, 17, tzinfo=timezone.utc)
        middle = datetime(2026, 11, 19, 7, tzinfo=timezone.utc)
        at_end = datetime(2026, 11, 19, 17, tzinfo=timezone.utc)

        def citation(key, name, index=0, **other):
            return {"document_id": str(key), "filename": name, "chunk_index": index, **other}

        def message(session, stamp, sources):
            row = Message(id=uuid4(), conversation_id=conversation_id, role="assistant",
                          content="private answer", citations=sources, created_at=stamp)
            session.add(row)
            return row.id

        def turn(session, stamp, *, state="completed", outcome="answered", source=None,
                 version=1, routes=("internal",), finished_at=None):
            session.add(QuestionTurn(
                user_id=self.db.admin, request_id=uuid4(), attempt_id=uuid4(), fingerprint="private fingerprint",
                received_at=stamp, finished_at=None if state == "running" else finished_at or stamp,
                state=state, outcome=outcome, planned_routes=list(routes), executed_routes=list(routes),
                reasons=[], assistant_message_id=source, citation_version=version,
            ))

        with self.db.sessions() as session:
            session.add(Conversation(id=conversation_id, user_id=self.db.admin, title="private title"))
            session.add(Document(id=document_id, filename="current.pdf", mime_type="application/pdf"))
            session.add(Document(id=gone, filename="old.pdf", mime_type="application/pdf"))
            session.flush()
            session.execute(delete(Document).where(Document.id == gone))

            first = message(session, at_start, [
                citation(document_id, "before.pdf", source_url="https://internal.example.test/secret"),
                citation(document_id, "before.pdf", 1, source_file_version_id=str(uuid4())),
                citation(gone, "earlier.pdf"),
                citation(uuid4(), "excluded", kind="web"),
            ])
            second = message(session, middle, [citation(gone, "last citation.pdf")])
            legacy = message(session, middle, [citation(document_id, "unverified.pdf")])
            excluded = message(session, at_end, [citation(document_id, "next day.pdf")])
            message(session, at_start, None)
            session.flush()
            turn(session, at_start, source=first, finished_at=at_end)
            turn(session, middle, source=second, outcome="partial", routes=("general", "internal"))
            turn(session, middle, source=legacy, version=None, outcome=None)
            turn(session, at_end, source=excluded)
            turn(session, middle, state="running", outcome=None, version=None)
            turn(session, middle, state="cancelled", outcome=None, version=None)
            turn(session, middle, state="failed", outcome="error", version=None, routes=())
            session.commit()

        response = self.db.client.get("/admin/statistics?from=2026-11-19&to=2026-11-20")
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["timezone"], "Asia/Ho_Chi_Minh")
        self.assertEqual(report["data_started_at"], "2026-11-18T17:00:00Z")
        self.assertEqual((report["outcome_denominator"], report["unclassified"], report["running"], report["cancelled"]),
                         (3, 2, 1, 1))
        self.assertEqual(report["daily_classified"], [{"date": "2026-11-19", "count": 3}])
        self.assertEqual(report["by_outcome"]["error"], {"count": 1, "ratio": 1 / 3})
        self.assertEqual(report["by_executed_route"]["mixed"]["count"], 1)
        self.assertEqual(report["by_executed_route"]["none"]["count"], 1)
        self.assertEqual(report["cited_answer_denominator"], 2)
        self.assertEqual(report["ranked_documents"], [
            {"document_id": str(gone), "count": 2, "ratio": 1., "filename": "last citation.pdf", "deleted": True},
            {"document_id": str(document_id), "count": 1, "ratio": .5, "filename": "current.pdf", "deleted": False},
        ])
        for private in ("private", str(conversation_id), "internal.example.test", "next day.pdf", "unverified.pdf"):
            self.assertNotIn(private, response.text)
        old = self.db.client.get("/admin/statistics?from=2026-11-17&to=2026-11-18").json()
        self.assertEqual(old["by_outcome"]["error"], {"count": None, "ratio": None})
        with patch("rag.admin_statistics.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 21, 12, tzinfo=ADMIN_TIMEZONE)
            multiple = self.db.client.get("/admin/statistics?from=2026-11-18&to=2026-11-23").json()
        self.assertEqual(multiple["daily_classified"], [
            {"date": "2026-11-18", "count": None}, {"date": "2026-11-19", "count": 3},
            {"date": "2026-11-20", "count": 1}, {"date": "2026-11-21", "count": 0},
            {"date": "2026-11-22", "count": None},
        ])
        self.assertEqual(multiple["outcome_denominator"], 4)
        self.assertEqual(self.db.client.get("/admin/statistics?from=2026-11-19&to=2026-11-19").status_code, 422)
        self.db.as_user(uuid4())
        self.assertEqual(self.db.client.get("/admin/statistics?from=2026-11-19&to=2026-11-20").status_code, 403)
