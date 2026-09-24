from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.langchain_retriever import SQLAlchemyVectorRetriever  # noqa: E402
from rag.retrieval import RetrievedChunk  # noqa: E402


class SQLAlchemyVectorRetrieverTests(unittest.TestCase):
    def test_invoke_delegates_once_and_maps_results_in_order(self) -> None:
        session = Mock(spec=Session)
        first_chunk_id = uuid4()
        first_document_id = uuid4()
        second_chunk_id = uuid4()
        second_document_id = uuid4()
        chunks = [
            RetrievedChunk(
                chunk_id=first_chunk_id,
                document_id=first_document_id,
                filename="handbook.pdf",
                chunk_index=4,
                content="First result",
                cosine_distance=0.1,
            ),
            RetrievedChunk(
                chunk_id=second_chunk_id,
                document_id=second_document_id,
                filename="policy.txt",
                chunk_index=1,
                content="Second result",
                cosine_distance=0.2,
            ),
        ]
        retriever = SQLAlchemyVectorRetriever(session=session, top_k=7)

        with patch(
            "rag.langchain_retriever.retrieve_chunks", return_value=chunks
        ) as retrieve:
            documents = retriever.invoke("graduation requirements")

        retrieve.assert_called_once_with(
            session, "graduation requirements", top_k=7
        )
        self.assertEqual(
            [document.page_content for document in documents],
            ["First result", "Second result"],
        )
        self.assertEqual(
            [document.metadata for document in documents],
            [
                {
                    "chunk_id": str(first_chunk_id),
                    "document_id": str(first_document_id),
                    "filename": "handbook.pdf",
                    "chunk_index": 4,
                    "cosine_distance": 0.1,
                },
                {
                    "chunk_id": str(second_chunk_id),
                    "document_id": str(second_document_id),
                    "filename": "policy.txt",
                    "chunk_index": 1,
                    "cosine_distance": 0.2,
                },
            ],
        )

    def test_invoke_returns_empty_results(self) -> None:
        session = Mock(spec=Session)
        retriever = SQLAlchemyVectorRetriever(session=session)

        with patch(
            "rag.langchain_retriever.retrieve_chunks", return_value=[]
        ) as retrieve:
            documents = retriever.invoke("unknown topic")

        self.assertEqual(documents, [])
        retrieve.assert_called_once_with(session, "unknown topic", top_k=5)

    def test_rejects_invalid_top_k_bounds(self) -> None:
        session = Mock(spec=Session)

        for top_k in (0, 21):
            with self.subTest(top_k=top_k):
                with self.assertRaises(ValidationError):
                    SQLAlchemyVectorRetriever(session=session, top_k=top_k)


if __name__ == "__main__":
    unittest.main()
