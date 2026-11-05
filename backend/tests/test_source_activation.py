"""Activation over real isolated transactions and retrieval SQL, with fake vectors."""
import json
import math
from hashlib import sha256
from pathlib import Path
import runpy
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4
from datetime import datetime, timezone

fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://offline:offline@localhost/offline")
sys.modules.setdefault("config", fake_config)

from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402
from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.sql.elements import BinaryExpression  # noqa: E402
from auth import AuthenticatedUser, get_authenticated_user  # noqa: E402
from config import settings  # noqa: E402
from database import Base  # noqa: E402
from main import app  # noqa: E402
from rag.ingestion import ingest_document  # noqa: E402
from rag.models import Chunk, Document, Message, SourceFileVersion  # noqa: E402
from rag.query_contract import QueryProcessingResult  # noqa: E402
from rag.retrieval import retrieve_candidates, retrieve_chunks  # noqa: E402
from rag.url_sources import FetchedSource, SourceFetchError  # noqa: E402
from test_extraction import create_two_page_pdf  # noqa: E402
import test_source_file_versions_integration as sqlite_fixture  # noqa: E402


@compiles(BinaryExpression, "sqlite")
def sqlite_vector_distance(expression, compiler, **kw):
    if getattr(expression.operator, "opstring", None) == "<=>":
        return f"cosine_distance({compiler.process(expression.left, **kw)}, {compiler.process(expression.right, **kw)})"
    return sqlite_fixture.sqlite_containment(expression, compiler, **kw)


class SourceActivationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = Path(temporary.name) / "originals"
        self.engine = create_engine(f"sqlite:///{Path(temporary.name) / 'isolated.db'}", connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def functions(connection, _record):
            connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
            connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat())
            connection.execute("PRAGMA foreign_keys=ON")

            def cosine(left, right):
                a, b = json.loads(left), json.loads(right)
                return 1 - sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))

            def contains(document, requested):
                values = json.loads(document or "null") or []
                return int(all(any(all(item.get(key) == value for key, value in subset.items()) for item in values) for subset in json.loads(requested)))

            connection.create_function("cosine_distance", 2, cosine)
            connection.create_function("json_contains", 2, contains)

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.admin = uuid4()
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.as_user(self.admin)
        self.client = TestClient(app)

        def patched(target, **kwargs):
            p = patch(target, **kwargs); result = p.start(); self.addCleanup(p.stop); return result

        for module in ("router", "admin_router", "source_file_router", "conversation_router"):
            patched(f"rag.{module}.SessionLocal", new=self.sessions)
        p = patch.object(settings, "admin_user_id", self.admin, create=True)
        p.start(); self.addCleanup(p.stop)
        patched("rag.source_files.source_file_directory", return_value=self.storage)
        self.embed = patched("rag.ingestion.embed_documents", side_effect=lambda texts: [[1.0] + [0.0]*767 for _ in texts])
        patched("rag.retrieval.embed_query", return_value=[1.0] + [0.0]*767)
        patched("rag.qa.process_query", return_value=QueryProcessingResult("search", "Question", None, False, 1))
        self.model = patched("rag.langchain_pipeline._get_chat_model", return_value=RunnableLambda(lambda _: "Answer [1]."))

    def as_user(self, user_id):
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(user_id)

    def seed(self, kind="file"):
        with self.sessions() as session:
            return ingest_document(session, "old.txt", "text/plain", b"old document", **(
                {"source_url": "https://www.vlu.edu.vn/isolated-activation"} if kind == "url" else {}
            )).id

    def status(self, source_id, active):
        return self.client.patch(f"/admin/knowledge-sources/{source_id}/status", json={"is_active": active})

    def test_migration_extends_file_versions_and_backfills_old_and_new_rows(self):
        backend = Path(__file__).resolve().parents[1]
        graph = ScriptDirectory(str(backend / "migrations"))
        self.assertEqual(graph.get_heads(), ["a7e3c9d1b502"])
        self.assertEqual(graph.get_revision("a7e3c9d1b502").down_revision, "c2a1e8d4f6b0")
        migration = runpy.run_path(str(backend / "migrations/versions/a7e3c9d1b502_add_source_is_active.py"))
        with create_engine("sqlite://").begin() as connection:
            connection.exec_driver_sql("CREATE TABLE documents (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO documents (id) VALUES (1)")
            with Operations.context(MigrationContext.configure(connection)):
                migration["upgrade"]()
                connection.exec_driver_sql("INSERT INTO documents (id) VALUES (2)")
                self.assertEqual(connection.exec_driver_sql("SELECT is_active FROM documents ORDER BY id").scalars().all(), [1, 1])
                migration["downgrade"]()
            self.assertEqual(connection.exec_driver_sql("SELECT id FROM documents ORDER BY id").scalars().all(), [1, 2])

    def test_status_is_admin_only_strict_idempotent_and_does_not_reindex(self):
        source_id = self.seed()
        self.embed.reset_mock()
        first = self.status(source_id, False)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.status(source_id, False)
        self.assertEqual(first.json()["updated_at"].rstrip("Z"), second.json()["updated_at"].rstrip("Z"))
        for invalid in ("false", 0, None):
            self.assertEqual(self.status(source_id, invalid).status_code, 422)
        self.assertEqual(self.client.patch(f"/admin/knowledge-sources/{source_id}/status", json={"is_active": False, "filename": "ignored"}).status_code, 422)
        self.assertEqual(self.status(uuid4(), False).status_code, 404)
        self.assertEqual(self.status(source_id, True).json()["is_active"], True)
        self.embed.assert_not_called()
        self.as_user(uuid4())
        self.assertEqual(self.status(source_id, False).status_code, 403)
        del app.dependency_overrides[get_authenticated_user]
        self.assertEqual(self.status(source_id, False).status_code, 401)

    def test_state_filter_counts_pages_and_detail_without_hiding_disabled_sources(self):
        enabled = self.seed()
        disabled = self.seed("url")
        self.assertEqual(self.status(disabled, False).status_code, 200)
        for query, ids in (("", {enabled, disabled}), ("?is_active=true", {enabled}), ("?is_active=false", {disabled})):
            response = self.client.get("/admin/knowledge-sources" + query)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], len(ids))
            self.assertEqual({UUID(row["id"]) for row in response.json()["items"]}, ids)
        page = self.client.get("/admin/knowledge-sources?is_active=false&limit=1&offset=1").json()
        self.assertEqual((page["total"], page["items"]), (1, []))
        self.assertFalse(self.client.get(f"/admin/knowledge-sources/{disabled}").json()["is_active"])
        self.assertEqual(self.client.get("/admin/knowledge-sources?is_active=invalid").status_code, 422)

    def test_active_filter_executes_before_top_k_and_downstream_reranking(self):
        disabled = self.seed()
        enabled = self.seed()
        self.status(disabled, False)
        with self.sessions() as session:
            # Disabled document is a closer match; filtering after LIMIT 1 would
            # starve the enabled result instead of returning it.
            session.scalar(select(Chunk).where(Chunk.document_id == enabled)).embedding = [.9, .1] + [0.0]*766
            session.commit()
        for retrieve in (retrieve_chunks, retrieve_candidates):
            with self.subTest(retrieve=retrieve.__name__), self.sessions() as session:
                with patch.object(session, "execute", wraps=session.execute) as execute:
                    result = retrieve(session, "Question", top_k=1)
                self.assertEqual([row.document_id for row in result], [enabled])
                sql = str(execute.call_args.args[0])
                self.assertLess(sql.index("documents.is_active IS true"), sql.index("LIMIT"))
        with self.sessions() as session:
            candidates = retrieve_candidates(session, "Question", top_k=20)
        scorer = Mock(side_effect=lambda rows: list(reversed(rows)))
        self.assertEqual([row.document_id for row in scorer(candidates)], [enabled])
        self.status(disabled, True)
        with self.sessions() as session:
            self.assertEqual(retrieve_chunks(session, "Question", top_k=1)[0].document_id, disabled)

    def test_disabled_file_replacement_and_url_refresh_keep_disabled_state(self):
        for mime, name, content in (
            ("text/plain", "new.txt", b"replacement text"),
            ("application/pdf", "new.pdf", create_two_page_pdf("New page", "Last page")),
        ):
            source_id = self.seed()
            self.status(source_id, False)
            response = self.client.put(f"/admin/knowledge-sources/{source_id}/file", files={"file": (name, content, mime)})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(self.client.get(f"/admin/knowledge-sources/{source_id}").json()["is_active"])
            with self.sessions() as session:
                version = session.scalar(select(SourceFileVersion).where(SourceFileVersion.document_id == source_id).order_by(SourceFileVersion.created_at.desc()))
            self.assertEqual(self.client.get(f"/source-files/{version.id}").content, content)
        source_id = self.seed("url")
        self.status(source_id, False)
        with patch("rag.admin_router.fetch_source", side_effect=SourceFetchError("offline")):
            self.assertEqual(self.client.post(f"/admin/knowledge-sources/{source_id}/refresh").status_code, 502)
        with self.sessions() as session:
            self.assertEqual(session.get(Document, source_id).content_hash, sha256(b"old document").hexdigest())
        fetched = FetchedSource("https://www.vlu.edu.vn/isolated-activation", "updated.txt", "text/plain", b"new URL bytes")
        with patch("rag.admin_router.fetch_source", return_value=fetched):
            response = self.client.post(f"/admin/knowledge-sources/{source_id}/refresh")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.client.get(f"/admin/knowledge-sources/{source_id}").json()["is_active"])

    def test_toggle_preserves_saved_answers_citations_and_original_access(self):
        source_id = self.seed()
        owner = uuid4()
        self.as_user(owner)
        first = self.client.post("/questions", json={"question": "Question"})
        self.assertEqual(first.status_code, 200, first.text)
        version_id = first.json()["sources"][0]["source_file_version_id"]
        with self.sessions() as session:
            saved = [(row.id, row.content, row.citations) for row in session.scalars(select(Message)).all()]
        self.as_user(self.admin)
        self.status(source_id, False)
        self.as_user(owner)
        paused = self.client.post("/questions", json={"question": "Question"})
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertEqual(paused.json()["sources"], [])
        self.assertEqual(self.client.get(f"/source-files/{version_id}").content, b"old document")
        self.as_user(self.admin)
        self.status(source_id, True)
        self.as_user(owner)
        resumed = self.client.post("/questions", json={"question": "Question"})
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["sources"][0]["document_id"], str(source_id))
        self.assertEqual(self.model.call_count, 2)
        with self.sessions() as session:
            self.assertEqual([(session.get(Message, id).id, session.get(Message, id).content, session.get(Message, id).citations) for id, _, _ in saved], saved)

    def test_failed_status_and_replacement_commits_roll_back_inactive_source(self):
        source_id = self.seed()
        with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private failure")):
            self.assertEqual(self.status(source_id, False).status_code, 503)
        with self.sessions() as session:
            self.assertTrue(session.get(Document, source_id).is_active)
        self.status(source_id, False)
        with self.sessions() as session:
            old_hash = session.get(Document, source_id).content_hash
            old_chunks = session.scalars(select(Chunk.id).where(Chunk.document_id == source_id)).all()
        old_files = {p.name: p.read_bytes() for p in self.storage.iterdir()}
        with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private failure")):
            response = self.client.put(f"/admin/knowledge-sources/{source_id}/file", files={"file": ("new.txt", b"new bytes", "text/plain")})
        self.assertEqual(response.status_code, 503)
        with self.sessions() as session:
            self.assertFalse(session.get(Document, source_id).is_active)
            self.assertEqual(session.get(Document, source_id).content_hash, old_hash)
            self.assertEqual(session.scalars(select(Chunk.id).where(Chunk.document_id == source_id)).all(), old_chunks)
        self.assertEqual({p.name: p.read_bytes() for p in self.storage.iterdir()}, old_files)


if __name__ == "__main__":
    unittest.main()
