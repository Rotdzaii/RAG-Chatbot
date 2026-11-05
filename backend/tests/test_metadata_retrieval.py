"""Metadata + activation through real isolated SQL and HTTP, without providers."""
from hashlib import sha256
import json
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

import test_source_activation as activation_fixture
from test_extraction import create_two_page_pdf
from rag.ingestion import ingest_document
from rag.models import Chunk, Document, Message
from rag.qa import answer_question
from rag.retrieval import retrieve_candidates, retrieve_chunks
from rag.source_metadata import RetrievalFilters
from rag.url_sources import FetchedSource
import rag.qa as qa_module


class MetadataRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = activation_fixture.SourceActivationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.sessions = self.fixture.sessions
        self.query = qa_module.process_query

    def seed(self, category=None, audience=None, *, active=True, vector=None, kind="file"):
        with self.sessions() as session:
            document = ingest_document(
                session, "fixture.txt", "text/plain", b"fixture context",
                category=category, audience=audience,
                **({"source_url": f"https://www.vlu.edu.vn/fixture-{uuid4()}"} if kind == "url" else {}),
            )
            document.is_active = active
            if vector:
                session.scalar(select(Chunk).where(Chunk.document_id == document.id)).embedding = vector + [0.0]*766
            session.commit()
            return document.id

    def corpus(self):
        disabled = self.seed("policy", "staff", active=False, vector=[1, 0])
        wrong = self.seed("other", "staff", vector=[.9999, .0001])
        matching = self.seed("policy", "staff", vector=[.9, .1])
        students = self.seed("policy", "students", vector=[.8, .2])
        unlabeled = self.seed(vector=[.999, .001])
        case = self.seed("Policy", "staff", vector=[.998, .002])
        return disabled, wrong, matching, students, unlabeled, case

    def test_metadata_and_active_predicates_execute_before_top_k_and_candidate_limit(self):
        disabled, wrong, matching, students, unlabeled, case = self.corpus()
        filters = RetrievalFilters(category=" policy ", audience=" staff ")
        for retrieve in (retrieve_chunks, retrieve_candidates):
            with self.subTest(retrieve=retrieve.__name__), self.sessions() as session:
                with patch.object(session, "execute", wraps=session.execute) as execute:
                    selected = retrieve(session, "Question", top_k=1, filters=filters)
                self.assertEqual([row.document_id for row in selected], [matching])
                statement = execute.call_args.args[0]
                sql = str(statement)
                for predicate in ("documents.is_active IS true", "documents.category =", "documents.audience ="):
                    self.assertLess(sql.index(predicate), sql.index("LIMIT"))
                self.assertNotIn("documents.category IS NULL", sql)
                self.assertNotIn("documents.audience IS NULL", sql)
                self.assertEqual(statement._limit_clause.value, 1)
            with self.sessions() as session:
                self.assertEqual(retrieve(session, "Question", filters=RetrievalFilters(category="missing")), [])
                result = retrieve(session, "Question", top_k=20, filters=RetrievalFilters(category="Policy"))
                self.assertEqual([row.document_id for row in result], [case])
                result = retrieve(session, "Question", top_k=20, filters=RetrievalFilters(category="policy"))
                self.assertEqual({row.document_id for row in result}, {matching, students})
                result = retrieve(session, "Question", top_k=20)
                self.assertEqual({row.document_id for row in result}, {wrong, matching, students, unlabeled, case})
                self.assertNotIn(disabled, {row.document_id for row in result})

    def test_omitted_null_and_empty_filters_keep_the_unfiltered_sql(self):
        self.corpus()
        for retrieve in (retrieve_chunks, retrieve_candidates):
            statements, results = [], []
            for kwargs in ({}, {"filters": None}, {"filters": RetrievalFilters()}):
                with self.sessions() as session, patch.object(session, "execute", wraps=session.execute) as execute:
                    results.append([row.chunk_id for row in retrieve(session, "Question", **kwargs)])
                    statements.append(str(execute.call_args.args[0]))
            self.assertEqual(statements, [statements[0]]*3)
            self.assertEqual(results, [results[0]]*3)

    def test_http_uploads_persist_metadata_and_are_available_to_scoped_questions(self):
        for kind in ("pdf", "txt", "url"):
            with self.subTest(kind=kind):
                metadata = {"category": f"  policy   {kind} ", "audience": " staff  members "}
                if kind == "url":
                    url = "https://www.vlu.edu.vn/upload-fixture"
                    with patch("rag.admin_router.fetch_source", return_value=FetchedSource(url, "page.html", "text/html", b"<p>fixture context</p>")):
                        response = self.client.post("/admin/knowledge-sources/url", json={"url": url, **metadata})
                else:
                    content = create_two_page_pdf("First page", "Second page") if kind == "pdf" else b"fixture context"
                    mime = "application/pdf" if kind == "pdf" else "text/plain"
                    response = self.client.post("/documents", files={"file": (f"fixture.{kind}", content, mime)}, data=metadata)
                self.assertEqual(response.status_code, 201, response.text)
                source_id = response.json()["document_id"]
                with self.sessions() as session:
                    document = session.get(Document, UUID(source_id))
                    self.assertEqual((document.category, document.audience), (f"policy {kind}", "staff members"))
                answer = self.client.post("/questions", json={"question": "Question", "filters": metadata})
                self.assertEqual(answer.status_code, 200, answer.text)
                self.assertEqual({source["document_id"] for source in answer.json()["sources"]}, {source_id})

    def test_http_scope_is_explicit_through_qa_history_and_no_filter_response_is_unchanged(self):
        _, wrong, matching, _, _, _ = self.corpus()
        with patch("rag.router.answer_question", wraps=answer_question) as ask:
            first = self.client.post("/questions", json={"question": "policy staff"})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(set(first.json()), {"answer", "sources", "conversation_id"})
            self.assertEqual(first.json()["sources"][0]["document_id"], str(wrong))
            self.assertNotIn("filters", ask.call_args.kwargs)
            self.query.assert_called_once_with("policy staff", ())
            conversation = first.json()["conversation_id"]
            scoped = self.client.post("/questions", json={
                "question": "Follow-up", "conversation_id": conversation,
                "filters": {"category": " policy ", "audience": " staff "},
            })
            self.assertEqual(scoped.status_code, 200, scoped.text)
            self.assertEqual(scoped.json()["sources"][0]["document_id"], str(matching))
            self.assertEqual(ask.call_args.kwargs["filters"], RetrievalFilters(category="policy", audience="staff"))
            self.assertEqual(self.query.call_args.args[0], "Follow-up")
            self.assertEqual(len(self.query.call_args.args[1]), 2)
            unscoped = self.client.post("/questions", json={"question": "Next question", "conversation_id": conversation})
            self.assertEqual(unscoped.status_code, 200, unscoped.text)
            self.assertEqual(unscoped.json()["sources"][0]["document_id"], str(wrong))
            self.assertNotIn("filters", ask.call_args.kwargs)

    def test_sse_preserves_old_unfiltered_fingerprint_and_detects_scope_change_on_retry(self):
        _, _, matching, _, _, _ = self.corpus()
        request_id = uuid4()
        body = {"question": "Question", "request_id": str(request_id)}

        def stream(payload):
            response = self.client.post("/questions/stream", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            return [(lines[0][7:], json.loads(lines[1][6:])) for frame in response.text.split("\n\n") if (lines := frame.splitlines()) and lines[0].startswith("event:")]

        first = stream(body)
        self.assertEqual(first[-1][0], "result")
        legacy = json.dumps({"question": "Question", "top_k": 5, "conversation_id": None}, separators=(",", ":"))
        with self.sessions() as session:
            message = session.get(Message, uuid5(self.fixture.admin, f"question:{request_id}:user"))
            self.assertEqual(message.citations, [{"request_fingerprint": sha256(legacy.encode()).hexdigest()}])
        self.assertEqual(stream({**body, "filters": {}})[-1], first[-1])
        conflict = stream({**body, "filters": {"category": "policy"}})
        self.assertEqual((conflict[-1][0], conflict[-1][1]["status"]), ("error", 409))
        self.assertEqual(self.query.call_count, 1)
        scoped = {**body, "request_id": str(uuid4()), "filters": {"category": "policy", "audience": "staff"}}
        response = stream(scoped)
        self.assertEqual(response[-1][1]["response"]["sources"][0]["document_id"], str(matching))
        self.assertEqual(stream({**scoped, "filters": {"category": " policy ", "audience": " staff "}})[-1], response[-1])
        self.assertEqual(self.query.call_count, 2)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(Message.id))), 4)

    def test_file_replacement_and_url_refresh_preserve_stored_metadata_and_inactive_state(self):
        for kind in ("file", "url"):
            document_id = self.seed("policy", "staff", kind=kind, active=False)
            with self.sessions() as session:
                document = session.get(Document, document_id)
                document.category, document.audience = " legacy category ", " legacy  audience "
                url = document.source_url
                session.commit()
            for content in (b"fixture context", b"replacement context"):
                if kind == "file":
                    response = self.client.put(f"/admin/knowledge-sources/{document_id}/file", files={"file": ("new.txt", content, "text/plain")})
                else:
                    with patch("rag.admin_router.fetch_source", return_value=FetchedSource(url, "new.txt", "text/plain", content)):
                        response = self.client.post(f"/admin/knowledge-sources/{document_id}/refresh")
                self.assertEqual(response.status_code, 200, response.text)
                with self.sessions() as session:
                    document = session.get(Document, document_id)
                    self.assertEqual((document.category, document.audience), (" legacy category ", " legacy  audience "))
                    self.assertFalse(document.is_active)

    def test_real_metadata_patch_and_list_compose_with_activation_and_rollback(self):
        matching = self.seed("policy", "staff", active=False)
        other = self.seed("other", "staff")
        listing = self.client.get("/admin/knowledge-sources", params={"category": " policy ", "audience": " staff ", "is_active": "false", "limit": 1})
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual((listing.json()["total"], listing.json()["items"][0]["id"]), (1, str(matching)))
        self.fixture.embed.reset_mock()
        response = self.client.patch(f"/admin/knowledge-sources/{matching}/metadata", json={"category": " New   Policy "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["category"], response.json()["audience"]), ("New Policy", "staff"))
        self.assertEqual(self.client.patch(f"/admin/knowledge-sources/{matching}/metadata", json={"audience": None}).status_code, 200)
        with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private detail")):
            response = self.client.patch(f"/admin/knowledge-sources/{matching}/metadata", json={"category": "discarded"})
        self.assertEqual(response.status_code, 503)
        self.fixture.embed.assert_not_called()
        with self.sessions() as session:
            document = session.get(Document, matching)
            self.assertEqual((document.category, document.audience, document.is_active), ("New Policy", None, False))
            self.assertEqual(session.get(Document, other).category, "other")

    def test_question_filter_validation_precedes_database_for_json_and_sse(self):
        with patch("rag.router.SessionLocal") as sessions:
            for filters in ({"category": " "}, {"audience": 32}, {"major": "Marketing"}, {"category": "x", "is_active": False}):
                for path in ("/questions", "/questions/stream"):
                    body = {"question": "Question", "filters": filters}
                    if path.endswith("stream"):
                        body["request_id"] = str(uuid4())
                    self.assertEqual(self.client.post(path, json=body).status_code, 422)
            sessions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
