import math
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rag.embeddings import (
    MODEL,
    OUTPUT_DIMENSIONALITY,
    _get_client,
    embed_documents,
    embed_query,
)


def embedding_response(*vectors: list[float]) -> SimpleNamespace:
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=vector) for vector in vectors]
    )


class EmbeddingTests(unittest.TestCase):
    def test_embeds_and_normalizes_documents(self) -> None:
        client = Mock()
        vector = [3.0, 4.0] + [0.0] * (OUTPUT_DIMENSIONALITY - 2)
        client.models.embed_content.return_value = embedding_response(vector)

        with patch("rag.embeddings._get_client", return_value=client):
            vectors = embed_documents(["document text"])

        self.assertEqual(len(vectors), 1)
        self.assertAlmostEqual(vectors[0][0], 0.6)
        self.assertAlmostEqual(vectors[0][1], 0.8)
        call = client.models.embed_content.call_args
        self.assertEqual(call.kwargs["model"], MODEL)
        self.assertEqual(call.kwargs["contents"], ["document text"])
        self.assertEqual(call.kwargs["config"].task_type, "RETRIEVAL_DOCUMENT")
        self.assertEqual(call.kwargs["config"].output_dimensionality, 768)
        client.close.assert_called_once_with()

    def test_embeds_and_normalizes_query(self) -> None:
        client = Mock()
        vector = [5.0] + [0.0] * (OUTPUT_DIMENSIONALITY - 1)
        client.models.embed_content.return_value = embedding_response(vector)

        with patch("rag.embeddings._get_client", return_value=client):
            result = embed_query("query text")

        self.assertEqual(result[0], 1.0)
        self.assertEqual(client.models.embed_content.call_args.kwargs["config"].task_type, "RETRIEVAL_QUERY")
        client.close.assert_called_once_with()

    def test_rejects_blank_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "Document texts"):
            embed_documents([" "])

        with self.assertRaisesRegex(ValueError, "Query text"):
            embed_query("\n")

    def test_rejects_zero_vector(self) -> None:
        client = Mock()
        client.models.embed_content.return_value = embedding_response(
            [0.0] * OUTPUT_DIMENSIONALITY
        )

        with patch("rag.embeddings._get_client", return_value=client):
            with self.assertRaisesRegex(ValueError, "must not be zero"):
                embed_query("query")

        client.close.assert_called_once_with()

    def test_rejects_wrong_vector_dimension(self) -> None:
        client = Mock()
        client.models.embed_content.return_value = embedding_response([1.0])

        with patch("rag.embeddings._get_client", return_value=client):
            with self.assertRaisesRegex(ValueError, "768 dimensions"):
                embed_query("query")

        client.close.assert_called_once_with()

    def test_rejects_response_count_mismatch(self) -> None:
        client = Mock()
        client.models.embed_content.return_value = embedding_response(
            [1.0] * OUTPUT_DIMENSIONALITY
        )

        with patch("rag.embeddings._get_client", return_value=client):
            with self.assertRaisesRegex(ValueError, "count mismatch"):
                embed_documents(["one", "two"])

        client.close.assert_called_once_with()

    def test_requires_gemini_api_key_when_creating_client(self) -> None:
        fake_config = SimpleNamespace(
            settings=SimpleNamespace(gemini_api_key=None)
        )

        with patch.dict(sys.modules, {"config": fake_config}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                _get_client()


if __name__ == "__main__":
    unittest.main()
