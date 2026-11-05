"""Offline Settings precedence and model selection through the real chat flow."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError
from sqlalchemy.orm import Session

fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://offline:offline@localhost/offline"
)
sys.modules.setdefault("config", fake_config)

from rag.qa import answer_question  # noqa: E402
from rag.query_contract import QueryDecision  # noqa: E402
from rag.retrieval import RetrievedChunk  # noqa: E402


def load_settings(*, dotenv=None, environment=None):
    """Load the actual config without reading a deployment .env or API key."""
    config_path = Path(__file__).resolve().parents[1] / "config.py"
    previous_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / ".env").write_text(
            "\n".join(f"{key}={value}" for key, value in (dotenv or {}).items()),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql+psycopg://offline:offline@localhost/offline",
            "GEMINI_API_KEY": "offline-test-key",
            **(environment or {}),
        }, clear=True):
            try:
                os.chdir(directory)
                return runpy.run_path(str(config_path))["settings"]
            finally:
                os.chdir(previous_cwd)


class ChatModelConfigTests(unittest.TestCase):
    def assert_chat_uses(self, settings, query_model, generation_model):
        config = ModuleType("config")
        config.settings = settings
        query_provider = Mock()
        query_provider.with_structured_output.return_value.invoke.return_value = (
            QueryDecision(action="search", standalone_query="Offline question")
        )
        generation_provider = RunnableLambda(lambda _: AIMessage(content="Offline answer [1]"))
        chunk = RetrievedChunk(
            chunk_id=uuid4(), document_id=uuid4(), filename="offline.txt",
            chunk_index=0, content="Offline context", cosine_distance=0.1,
        )
        with (
            patch.dict(sys.modules, {"config": config}),
            patch("rag.query_processing.ChatGoogleGenerativeAI", return_value=query_provider) as query,
            patch("rag.langchain_pipeline.ChatGoogleGenerativeAI", return_value=generation_provider) as generation,
            patch("rag.langchain_retriever.retrieve_chunks", return_value=[chunk]),
        ):
            result = answer_question(Mock(spec=Session), "Offline question")

        self.assertEqual(result.answer, "Offline answer [1]")
        self.assertEqual(result.sources[0].chunk_id, chunk.chunk_id)
        query.assert_called_once_with(model=query_model, api_key=settings.gemini_api_key)
        generation.assert_called_once_with(model=generation_model, api_key=settings.gemini_api_key)

    def test_no_override_uses_36_for_query_and_generation(self):
        settings = load_settings()
        self.assertEqual(settings.rag_query_model, "gemini-3.6-flash")
        self.assertEqual(settings.rag_generation_model, "gemini-3.6-flash")
        self.assert_chat_uses(settings, "gemini-3.6-flash", "gemini-3.6-flash")

    def test_dotenv_override_uses_38_for_query_and_generation(self):
        settings = load_settings(dotenv={
            "RAG_QUERY_MODEL": "gemini-3.8-flash",
            "RAG_GENERATION_MODEL": "gemini-3.8-flash",
        })
        self.assert_chat_uses(settings, "gemini-3.8-flash", "gemini-3.8-flash")

    def test_environment_override_38_takes_precedence_over_dotenv_36(self):
        settings = load_settings(
            dotenv={"RAG_QUERY_MODEL": "gemini-3.6-flash", "RAG_GENERATION_MODEL": "gemini-3.6-flash"},
            environment={"RAG_QUERY_MODEL": "gemini-3.8-flash", "RAG_GENERATION_MODEL": "gemini-3.8-flash"},
        )
        self.assert_chat_uses(settings, "gemini-3.8-flash", "gemini-3.8-flash")

    def test_query_override_does_not_change_generation_default(self):
        settings = load_settings(environment={"RAG_QUERY_MODEL": "gemini-3.8-flash"})
        self.assert_chat_uses(settings, "gemini-3.8-flash", "gemini-3.6-flash")

    def test_invalid_model_is_rejected_for_either_step(self):
        for variable in ("RAG_QUERY_MODEL", "RAG_GENERATION_MODEL"):
            with self.subTest(variable=variable), self.assertRaises(ValidationError):
                load_settings(environment={variable: "invalid-model"})

    def test_embedding_and_legacy_benchmark_model_constants_are_unchanged(self):
        from rag.embeddings import MODEL as embedding_model, OUTPUT_DIMENSIONALITY
        from rag.langchain_pipeline import MODEL as benchmark_generation_model
        from rag.query_contract import QUERY_PROCESSING_MODEL, query_processing_config

        self.assertEqual((embedding_model, OUTPUT_DIMENSIONALITY), ("gemini-embedding-001", 768))
        self.assertEqual(benchmark_generation_model, "gemini-3.8-flash")
        self.assertEqual(QUERY_PROCESSING_MODEL, "gemini-3.8-flash")
        self.assertEqual(query_processing_config()["model"], "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
