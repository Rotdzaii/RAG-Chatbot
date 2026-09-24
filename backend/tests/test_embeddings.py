import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rag.embeddings import (
    MODEL,
    OUTPUT_DIMENSIONALITY,
    _get_embeddings,
    embed_documents,
    embed_query,
)


class EmbeddingTests(unittest.TestCase):
    def test_embeds_and_normalizes_documents(self) -> None:
        embeddings = Mock()
        vector = [3.0, 4.0] + [0.0] * (OUTPUT_DIMENSIONALITY - 2)
        embeddings.embed_documents.return_value = [vector]

        with patch("rag.embeddings._get_embeddings", return_value=embeddings):
            vectors = embed_documents(["document text"])

        self.assertEqual(len(vectors), 1)
        self.assertAlmostEqual(vectors[0][0], 0.6)
        self.assertAlmostEqual(vectors[0][1], 0.8)
        embeddings.embed_documents.assert_called_once_with(["document text"])
        embeddings.embed_query.assert_not_called()

    def test_embeds_and_normalizes_query(self) -> None:
        embeddings = Mock()
        vector = [5.0] + [0.0] * (OUTPUT_DIMENSIONALITY - 1)
        embeddings.embed_query.return_value = vector

        with patch("rag.embeddings._get_embeddings", return_value=embeddings):
            result = embed_query("query text")

        self.assertEqual(result[0], 1.0)
        embeddings.embed_query.assert_called_once_with("query text")
        embeddings.embed_documents.assert_not_called()

    def test_rejects_blank_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "Document texts"):
            embed_documents([" "])

        with self.assertRaisesRegex(ValueError, "Query text"):
            embed_query("\n")

    def test_rejects_zero_vector(self) -> None:
        embeddings = Mock()
        embeddings.embed_query.return_value = [0.0] * OUTPUT_DIMENSIONALITY

        with patch("rag.embeddings._get_embeddings", return_value=embeddings):
            with self.assertRaisesRegex(ValueError, "must not be zero"):
                embed_query("query")

    def test_rejects_wrong_vector_dimension(self) -> None:
        embeddings = Mock()
        embeddings.embed_query.return_value = [1.0]

        with patch("rag.embeddings._get_embeddings", return_value=embeddings):
            with self.assertRaisesRegex(ValueError, "768 dimensions"):
                embed_query("query")

    def test_rejects_response_count_mismatch(self) -> None:
        embeddings = Mock()
        embeddings.embed_documents.return_value = [
            [1.0] * OUTPUT_DIMENSIONALITY
        ]

        with patch("rag.embeddings._get_embeddings", return_value=embeddings):
            with self.assertRaisesRegex(ValueError, "count mismatch"):
                embed_documents(["one", "two"])

    def test_configures_langchain_embeddings_wrapper(self) -> None:
        secret = Mock()
        secret.get_secret_value.return_value = "test-api-key"
        fake_config = SimpleNamespace(
            settings=SimpleNamespace(gemini_api_key=secret)
        )

        with (
            patch.dict(sys.modules, {"config": fake_config}),
            patch(
                "rag.embeddings.GoogleGenerativeAIEmbeddings"
            ) as embeddings_class,
        ):
            result = _get_embeddings()

        self.assertIs(result, embeddings_class.return_value)
        secret.get_secret_value.assert_called_once_with()
        embeddings_class.assert_called_once_with(
            model=MODEL,
            api_key="test-api-key",
            output_dimensionality=OUTPUT_DIMENSIONALITY,
        )

    def test_requires_gemini_api_key_when_creating_wrapper(self) -> None:
        fake_config = SimpleNamespace(
            settings=SimpleNamespace(gemini_api_key=None)
        )

        with patch.dict(sys.modules, {"config": fake_config}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                _get_embeddings()


if __name__ == "__main__":
    unittest.main()
