import unittest
from unittest.mock import Mock, patch

from pypdf.errors import PdfReadError

from rag.extraction import extract_text


class ExtractTextTests(unittest.TestCase):
    def test_decodes_vietnamese_text_with_bom(self) -> None:
        expected = "Xin ch\u00e0o Vi\u1ec7t Nam"
        content = b"\xef\xbb\xbf" + expected.encode("utf-8")

        self.assertEqual(extract_text(content, "text/plain"), expected)

    def test_rejects_unsupported_mime_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported MIME type"):
            extract_text(b"image", "image/png")

    def test_rejects_invalid_utf8(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid UTF-8 text"):
            extract_text(b"\xff", "text/plain")

    @patch("rag.extraction.PdfReader")
    def test_joins_pdf_page_text_with_blank_lines(self, reader_class: Mock) -> None:
        first_page = Mock()
        first_page.extract_text.return_value = "Trang một"
        second_page = Mock()
        second_page.extract_text.return_value = "Trang hai"
        reader_class.return_value.pages = [first_page, second_page]

        result = extract_text(b"PDF", "application/pdf")

        self.assertEqual(result, "Trang một\n\nTrang hai")

    @patch("rag.extraction.PdfReader", side_effect=PdfReadError("invalid"))
    def test_rejects_invalid_pdf(self, reader_class: Mock) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid PDF file"):
            extract_text(b"not a PDF", "application/pdf")

    def test_rejects_empty_extracted_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "No text could be extracted"):
            extract_text(b" \n", "text/plain")


if __name__ == "__main__":
    unittest.main()
