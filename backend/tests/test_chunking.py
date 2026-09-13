import unittest

from rag.chunking import chunk_text


class ChunkTextTests(unittest.TestCase):
    def test_returns_short_text_as_one_chunk(self) -> None:
        self.assertEqual(chunk_text("short text"), ["short text"])

    def test_splits_long_text_into_sliding_windows(self) -> None:
        self.assertEqual(
            chunk_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, overlap=2),
            ["abcdefghij", "ijklmnopqr", "qrstuvwxyz"],
        )

    def test_preserves_requested_overlap(self) -> None:
        chunks = chunk_text("abcdefghijkl", chunk_size=5, overlap=2)

        self.assertEqual(chunks[0][-2:], chunks[1][:2])
        self.assertEqual(chunks[1][-2:], chunks[2][:2])

    def test_rejects_whitespace_only_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "Text must not be empty"):
            chunk_text(" \n\t ")

    def test_rejects_non_positive_chunk_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "chunk_size"):
            chunk_text("text", chunk_size=0)

    def test_rejects_invalid_overlap(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            chunk_text("text", chunk_size=4, overlap=4)

        with self.assertRaisesRegex(ValueError, "overlap"):
            chunk_text("text", chunk_size=4, overlap=-1)


if __name__ == "__main__":
    unittest.main()
