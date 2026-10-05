import inspect
import unittest
from unittest.mock import patch

from rag.chunking import chunk_text_with_offsets
from rag.index_provenance import (
    BASELINE_EMBEDDING_PROFILE,
    CHUNKING_PROFILE,
    current_embedding_profile,
)


class IndexProvenanceTests(unittest.TestCase):
    def test_chunking_profile_describes_ingestion_defaults(self) -> None:
        parameters = inspect.signature(chunk_text_with_offsets).parameters
        self.assertEqual(parameters["chunk_size"].default, 1000)
        self.assertEqual(parameters["overlap"].default, 150)
        if "align_to_words" in parameters:
            self.assertFalse(parameters["align_to_words"].default)
        self.assertEqual(CHUNKING_PROFILE, "fixed-character-window:1000:150:v1")

    def test_embedding_model_change_changes_current_profile(self) -> None:
        self.assertEqual(current_embedding_profile(), BASELINE_EMBEDDING_PROFILE)
        with patch("rag.index_provenance.MODEL", "replacement-model"):
            self.assertNotEqual(current_embedding_profile(), BASELINE_EMBEDDING_PROFILE)


if __name__ == "__main__":
    unittest.main()
