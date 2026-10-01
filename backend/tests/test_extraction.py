from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pypdf.errors import PdfReadError

from rag.extraction import extract_text


def create_two_page_pdf(first_page: str, second_page: str) -> bytes:
    def stream_object(text: str) -> bytes:
        escaped = (
            text.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
        return (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream_object(first_page),
        stream_object(second_page),
    )
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


class ExtractTextTests(unittest.TestCase):
    def test_decodes_vietnamese_text_with_bom(self) -> None:
        expected = "Xin chào Việt Nam"
        content = b"\xef\xbb\xbf" + expected.encode("utf-8")

        self.assertEqual(extract_text(content, "text/plain"), expected)

    def test_rejects_unsupported_mime_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported MIME type"):
            extract_text(b"image", "image/png")

    def test_rejects_invalid_utf8(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid UTF-8 text"):
            extract_text(b"\xff", "text/plain")

    def test_joins_real_pdf_page_text_with_blank_lines_and_cleans_up(self) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory) / "loader-input.pdf"
            with patch(
                "rag.extraction.NamedTemporaryFile",
                return_value=temporary_path.open("w+b"),
            ):
                result = extract_text(
                    create_two_page_pdf("Trang mot", "Trang hai"),
                    "application/pdf",
                )

            self.assertEqual(result, "Trang mot\n\nTrang hai")
            self.assertFalse(temporary_path.exists())

    def test_rejects_invalid_pdf_and_cleans_up(self) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory) / "invalid.pdf"
            with patch(
                "rag.extraction.NamedTemporaryFile",
                return_value=temporary_path.open("w+b"),
            ):
                with self.assertRaisesRegex(ValueError, "Invalid PDF file"):
                    extract_text(b"not a PDF", "application/pdf")

            self.assertFalse(temporary_path.exists())

    def test_rejects_pdf_without_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "No text could be extracted"):
            extract_text(create_two_page_pdf("", ""), "application/pdf")

    @patch("rag.extraction.PyPDFLoader.load", side_effect=PdfReadError("invalid"))
    def test_cleans_up_when_loader_raises(self, _loader: object) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory) / "loader-error.pdf"
            with patch(
                "rag.extraction.NamedTemporaryFile",
                return_value=temporary_path.open("w+b"),
            ):
                with self.assertRaisesRegex(ValueError, "Invalid PDF file"):
                    extract_text(b"PDF", "application/pdf")

            self.assertFalse(temporary_path.exists())

    @patch("rag.extraction.PyPDFLoader.load", side_effect=PermissionError("denied"))
    def test_does_not_mask_system_error_and_still_cleans_up(
        self, _loader: object
    ) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory) / "system-error.pdf"
            with patch(
                "rag.extraction.NamedTemporaryFile",
                return_value=temporary_path.open("w+b"),
            ):
                with self.assertRaises(PermissionError):
                    extract_text(b"PDF", "application/pdf")

            self.assertFalse(temporary_path.exists())

    def test_write_error_closes_and_removes_temporary_file(self) -> None:
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory) / "write-error.pdf"
            file_handle = temporary_path.open("w+b")

            class WriteFailingTemporaryFile:
                name = file_handle.name

                def __enter__(self) -> "WriteFailingTemporaryFile":
                    return self

                def __exit__(self, *_args: object) -> None:
                    file_handle.close()

                def write(self, _content: bytes) -> int:
                    raise OSError("write failed")

            with patch(
                "rag.extraction.NamedTemporaryFile",
                return_value=WriteFailingTemporaryFile(),
            ):
                with self.assertRaisesRegex(OSError, "write failed"):
                    extract_text(b"PDF", "application/pdf")

            self.assertTrue(file_handle.closed)
            self.assertFalse(temporary_path.exists())

    def test_rejects_empty_extracted_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "No text could be extracted"):
            extract_text(b" \n", "text/plain")


if __name__ == "__main__":
    unittest.main()
