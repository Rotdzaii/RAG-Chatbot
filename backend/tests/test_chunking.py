import unittest

from rag.chunking import chunk_text, chunk_text_with_offsets


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

    def test_ingestion_default_retains_legacy_fixed_offsets(self) -> None:
        text = "words " * 300

        chunks = chunk_text_with_offsets(text)

        self.assertEqual(chunks[0].end_offset, 1000)
        self.assertEqual(chunks[1].start_offset, 850)
        self.assertEqual(chunks[1].content, text[850:1850].strip())

    def test_uses_nearby_word_boundaries_for_pdf_sized_text(self) -> None:
        text = ("Ngành Kỹ thuật phần mềm đào tạo kỹ năng lập trình ứng dụng. " * 45).strip()

        chunks = chunk_text_with_offsets(text, align_to_words=True)

        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            self.assertEqual(chunk.content, text[chunk.start_offset : chunk.end_offset])
            self.assertLessEqual(len(chunk.content), 1000)
            if chunk.start_offset > 0:
                self.assertFalse(
                    text[chunk.start_offset - 1].isalnum()
                    and text[chunk.start_offset].isalnum()
                )
            if chunk.end_offset < len(text):
                self.assertFalse(
                    text[chunk.end_offset - 1].isalnum()
                    and text[chunk.end_offset].isalnum()
                )

        for previous, current in zip(chunks, chunks[1:]):
            self.assertGreaterEqual(previous.end_offset, current.start_offset)
            self.assertGreaterEqual(previous.end_offset - current.start_offset, 100)
            self.assertLessEqual(previous.end_offset - current.start_offset, 200)

    def test_long_unbroken_text_still_makes_progress(self) -> None:
        text = "a" * 2300
        chunks = chunk_text_with_offsets(text, align_to_words=True)

        self.assertEqual([chunk.start_offset for chunk in chunks], [0, 850, 1700])
        self.assertEqual(chunks[-1].end_offset, len(text))

    def test_reports_offsets_after_trimming_chunk_whitespace(self) -> None:
        chunks = chunk_text_with_offsets("  abcdef  ", chunk_size=7, overlap=2)

        self.assertEqual(
            [
                (chunk.content, chunk.start_offset, chunk.end_offset)
                for chunk in chunks
            ],
            [("abcde", 2, 7), ("def", 5, 8)],
        )

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
