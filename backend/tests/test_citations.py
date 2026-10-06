import unittest

from rag.citations import cited_source_indices


class CitationTests(unittest.TestCase):
    def test_preserves_original_indices_and_deduplicates_groups(self) -> None:
        self.assertEqual(
            cited_source_indices("Một ý [2, 3], ý khác [1; 2].", 3),
            (2, 3, 1),
        )

    def test_ignores_markdown_links_and_handles_no_citations(self) -> None:
        self.assertEqual(cited_source_indices("[1](https://example.test) [2]", 2), (2,))
        self.assertEqual(cited_source_indices("Không đủ thông tin.", 3), ())

    def test_rejects_missing_and_zero_source_references(self) -> None:
        for answer, count in (("Câu trả lời [0]", 3), ("Câu trả lời [4]", 3),
                              ("Câu trả lời [1, 9]", 3), ("Câu trả lời [1]", 0)):
            with self.subTest(answer=answer, count=count):
                with self.assertRaisesRegex(ValueError, "invalid citation"):
                    cited_source_indices(answer, count)


if __name__ == "__main__":
    unittest.main()
