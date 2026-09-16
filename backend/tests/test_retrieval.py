import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.retrieval import MAX_COSINE_DISTANCE, RetrievedChunk, retrieve_chunks


class RetrieveChunksTests(unittest.TestCase):
    def test_embeds_once_and_returns_typed_results(self) -> None:
        session = Mock()
        chunk_id = uuid4()
        document_id = uuid4()
        session.execute.return_value.mappings.return_value = [
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "filename": "notes.txt",
                "chunk_index": 2,
                "content": "matching content",
                "cosine_distance": 0.25,
            }
        ]

        with patch("rag.retrieval.embed_query", return_value=[0.1] * 768) as embed:
            results = retrieve_chunks(session, "search phrase", top_k=3)

        self.assertEqual(
            results,
            [
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    filename="notes.txt",
                    chunk_index=2,
                    content="matching content",
                    cosine_distance=0.25,
                )
            ],
        )
        embed.assert_called_once_with("search phrase")
        session.execute.assert_called_once()

        statement = session.execute.call_args.args[0]
        statement_sql = str(statement)
        self.assertIn("JOIN documents", statement_sql)
        self.assertIn("chunks.embedding IS NOT NULL", statement_sql)
        self.assertIn("ORDER BY", statement_sql)
        self.assertEqual(statement._limit_clause.value, 3)

    def test_applies_distance_threshold_before_ordering_and_limit(self) -> None:
        session = Mock()
        session.execute.return_value.mappings.return_value = []

        with patch("rag.retrieval.embed_query", return_value=[0.1] * 768):
            retrieve_chunks(session, "search phrase", top_k=4)

        statement = session.execute.call_args.args[0]
        compiled = statement.compile()
        statement_sql = str(compiled)

        self.assertIn("<=", statement_sql)
        self.assertIn(MAX_COSINE_DISTANCE, compiled.params.values())
        self.assertLess(statement_sql.index("WHERE"), statement_sql.index("ORDER BY"))
        self.assertLess(statement_sql.index("ORDER BY"), statement_sql.index("LIMIT"))
        self.assertEqual(statement._limit_clause.value, 4)

    def test_rejects_blank_query_without_embedding_or_database_work(self) -> None:
        session = Mock()

        with patch("rag.retrieval.embed_query") as embed:
            with self.assertRaisesRegex(ValueError, "Query must not be blank"):
                retrieve_chunks(session, " \n")

        embed.assert_not_called()
        session.execute.assert_not_called()

    def test_rejects_invalid_top_k_without_embedding_or_database_work(self) -> None:
        session = Mock()

        with patch("rag.retrieval.embed_query") as embed:
            with self.assertRaisesRegex(ValueError, "top_k"):
                retrieve_chunks(session, "query", top_k=0)
            with self.assertRaisesRegex(ValueError, "top_k"):
                retrieve_chunks(session, "query", top_k=21)

        embed.assert_not_called()
        session.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
