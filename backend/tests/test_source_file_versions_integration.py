"""Version pinning through real upload/chat/replacement, with temporary DB/files."""
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import runpy
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.elements import BinaryExpression

fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://offline:offline@localhost/offline")
sys.modules.setdefault("config", fake_config)

from auth import AuthenticatedUser, get_authenticated_user, require_admin  # noqa: E402
from database import Base  # noqa: E402
from main import app  # noqa: E402
from rag.models import Chunk, Conversation, Document, Message, SourceFileVersion  # noqa: E402
from rag.query_contract import QueryProcessingResult  # noqa: E402
from rag.retrieval import RetrievedChunk  # noqa: E402
from test_extraction import create_two_page_pdf  # noqa: E402


@compiles(JSONB, "sqlite")
def sqlite_json(_type, compiler, **kw):
    return "JSON"


@compiles(VECTOR, "sqlite")
def sqlite_vector(_type, compiler, **kw):
    return "TEXT"


@compiles(BinaryExpression, "sqlite")
def sqlite_containment(expression, compiler, **kw):
    # Test-only equivalent for PostgreSQL JSONB containment. Ownership, role and
    # conversation joins still execute the production query against real rows.
    if getattr(expression.operator, "opstring", None) == "@>":
        return f"json_contains({compiler.process(expression.left, **kw)}, {compiler.process(expression.right, **kw)})"
    return compiler.visit_binary(expression, **kw)


class SourceFileVersionsIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = Path(temporary.name) / "originals"
        self.storage.mkdir()
        self.engine = create_engine(f"sqlite:///{Path(temporary.name) / 'isolated.db'}", connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def functions(connection, _record):
            connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
            connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat())
            connection.execute("PRAGMA foreign_keys=ON")

            def contains(document, requested):
                values = json.loads(document or "null") or []
                return int(all(any(all(item.get(key) == value for key, value in subset.items()) for item in values) for subset in json.loads(requested)))

            connection.create_function("json_contains", 2, contains)

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.user_id, self.admin_id = uuid4(), uuid4()
        self.active_document = None
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(self.admin_id)
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(self.user_id)
        self.client = TestClient(app)

        def patched(target, **kwargs):
            p = patch(target, **kwargs); result = p.start(); self.addCleanup(p.stop); return result

        for module in ("router", "admin_router", "source_file_router", "conversation_router"):
            patched(f"rag.{module}.SessionLocal", new=self.sessions)
        patched("rag.source_files.source_file_directory", return_value=self.storage)
        p = patch.object(sys.modules["config"].settings, "admin_user_id", self.admin_id, create=True)
        p.start(); self.addCleanup(p.stop)
        patched("rag.ingestion.embed_documents", side_effect=lambda texts: [[0.1] * 768 for _ in texts])
        patched("rag.qa.process_query", return_value=QueryProcessingResult("search", "Question", None, False, 1))
        patched("rag.langchain_pipeline._get_chat_model", return_value=RunnableLambda(lambda _: "Answer [1]."))

        def retrieve(session, _query, top_k=5):
            rows = session.execute(select(Chunk, Document).join(Document).where(Document.id == self.active_document)).all()
            return [RetrievedChunk(
                chunk_id=chunk.id, document_id=document.id, filename=document.filename,
                chunk_index=chunk.chunk_index, content=chunk.content, cosine_distance=.1,
                page_start=chunk.page_start, page_end=chunk.page_end,
                source_file_version_id=chunk.source_file_version_id, mime_type=document.mime_type,
                source_url=document.source_url,
            ) for chunk, document in rows][:top_k]

        patched("rag.langchain_retriever.retrieve_chunks", side_effect=retrieve)

    def upload(self, content=b"old source", mime="text/plain", name="source.txt"):
        response = self.client.post("/documents", files={"file": (name, content, mime)})
        self.assertEqual(response.status_code, 201, response.text)
        self.active_document = UUID(response.json()["document_id"])
        return self.active_document

    def ask(self, conversation_id=None):
        response = self.client.post("/questions", json={"question": "Question", **({"conversation_id": conversation_id} if conversation_id else {})})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pdf_and_txt_old_citation_still_opens_old_bytes_after_replacement(self):
        cases = (
            ("text/plain", "source.txt", b"original text", b"replacement text"),
            ("application/pdf", "source.pdf", create_two_page_pdf("Original page", "Old last"), create_two_page_pdf("Replacement page", "New last")),
        )
        for mime, name, old, new in cases:
            with self.subTest(mime=mime):
                document_id = self.upload(old, mime, name)
                first = self.ask()
                old_version = first["sources"][0]["source_file_version_id"]
                self.assertIsNotNone(old_version)
                self.assertEqual(self.client.get(f"/source-files/{old_version}").content, old)
                replaced = self.client.put(f"/admin/knowledge-sources/{document_id}/file", files={"file": ("revised-" + name, new, mime)})
                self.assertEqual(replaced.status_code, 200, replaced.text)
                with self.sessions() as session:
                    current = session.scalar(select(Chunk).where(Chunk.document_id == document_id))
                    new_version = str(current.source_file_version_id)
                self.assertNotEqual(old_version, new_version)
                # An uncited new version is not accessible to the ordinary user.
                self.assertEqual(self.client.get(f"/source-files/{new_version}").status_code, 404)
                second = self.ask(first["conversation_id"])
                self.assertEqual(second["sources"][0]["source_file_version_id"], new_version)
                self.assertEqual(self.client.get(f"/source-files/{new_version}").content, new)
                self.assertEqual(self.client.get(f"/source-files/{old_version}").content, old)
                history = self.client.get(f"/conversations/{first['conversation_id']}/messages").json()
                citations = [message["citations"][0] for message in history if message["role"] == "assistant"]
                self.assertEqual([item["source_file_version_id"] for item in citations], [old_version, new_version])
                # Deletion revokes every version while the saved answer remains.
                self.assertEqual(self.client.delete(f"/admin/knowledge-sources/{document_id}").status_code, 204)
                for version in (old_version, new_version):
                    self.assertEqual(self.client.get(f"/source-files/{version}").status_code, 404)
                with self.sessions() as session:
                    self.assertEqual(session.scalar(select(func.count(SourceFileVersion.id)).where(SourceFileVersion.document_id == document_id)), 0)
                    self.assertEqual(session.scalar(select(func.count(Message.id)).where(Message.conversation_id == UUID(first["conversation_id"]))), 4)
                self.assertEqual(list(self.storage.iterdir()), [])

    def test_owner_other_user_admin_and_forged_user_citation_permissions(self):
        self.upload()
        answer = self.ask()
        source = answer["sources"][0]
        path = f"/source-files/{source['source_file_version_id']}"
        outsider = uuid4()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(outsider)
        self.assertEqual(self.client.get(path).status_code, 404)
        with self.sessions() as session:
            conversation = Conversation(id=uuid4(), user_id=outsider, title="Other user", is_pinned=False)
            session.add(conversation)
            session.add(Message(id=uuid4(), conversation_id=conversation.id, role="user", content="Forged citation", citations=[source]))
            session.commit()
        self.assertEqual(self.client.get(path).status_code, 404)
        with self.sessions() as session:
            session.add(Message(id=uuid4(), conversation_id=conversation.id, role="assistant", content="Mismatched document", citations=[{**source, "document_id": str(uuid4())}]))
            session.commit()
        self.assertEqual(self.client.get(path).status_code, 404)
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(self.admin_id)
        self.assertEqual(self.client.get(path).status_code, 200)
        del app.dependency_overrides[get_authenticated_user]
        self.assertEqual(self.client.get(path).status_code, 401)

    def test_failed_upload_replace_and_delete_commit_preserve_storage_consistency(self):
        with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private error")):
            response = self.client.post("/documents", files={"file": ("source.txt", b"new bytes", "text/plain")})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(list(self.storage.iterdir()), [])
        document_id = self.upload()
        answer = self.ask()
        old_version = answer["sources"][0]["source_file_version_id"]
        before = {p.name: p.read_bytes() for p in self.storage.iterdir()}
        with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private error")):
            response = self.client.put(f"/admin/knowledge-sources/{document_id}/file", files={"file": ("new.txt", b"replacement", "text/plain")})
        self.assertEqual(response.status_code, 503)
        self.assertEqual({p.name: p.read_bytes() for p in self.storage.iterdir()}, before)
        with patch("sqlalchemy.orm.Session.commit", side_effect=SQLAlchemyError("private error")):
            response = self.client.delete(f"/admin/knowledge-sources/{document_id}")
        self.assertEqual(response.status_code, 503)
        self.assertEqual({p.name: p.read_bytes() for p in self.storage.iterdir()}, before)
        self.assertEqual(self.client.get(f"/source-files/{old_version}").content, b"old source")

    def test_migration_keeps_parent_and_generates_postgresql_foreign_key_ddl_offline(self):
        backend = Path(__file__).resolve().parents[1]
        graph = ScriptDirectory(str(backend / "migrations"))
        self.assertEqual(graph.get_heads(), ["a7e3c9d1b502"])
        self.assertEqual(graph.get_revision("c2a1e8d4f6b0").down_revision, "f9d4b2c7e501")
        migration = runpy.run_path(str(backend / "migrations/versions/c2a1e8d4f6b0_add_source_file_versions.py"))
        output = StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context):
            migration["upgrade"]()
        ddl = output.getvalue()
        self.assertIn("CREATE TABLE source_file_versions", ddl)
        self.assertIn("fk_chunks_source_file_version_id", ddl)
        self.assertIn("ON DELETE SET NULL", ddl)
        self.assertIn("ON DELETE CASCADE", ddl)


if __name__ == "__main__":
    unittest.main()
