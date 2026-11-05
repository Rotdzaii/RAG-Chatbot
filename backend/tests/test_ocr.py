from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
import pypdfium2  # Load native platform bindings before mocking subprocess.run.

from rag.extraction import extract_content
from rag.ocr import OCRFailed, OCRUnavailable, _run
from test_extraction import create_two_page_pdf


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(database_url="postgresql+psycopg://user:password@localhost/test")
sys.modules.setdefault("config", fake_config)


def scanned_pdf(*, blank: bool = False) -> bytes:
    with Image.new("RGB", (500, 200), "white") as image, BytesIO() as buffer:
        if not blank:
            ImageDraw.Draw(image).text((30, 50), "Scan: Admissions 2026", fill="black")
        image.save(buffer, format="PDF", resolution=150)
        return buffer.getvalue()


def mixed_pdf() -> bytes:
    native = PdfReader(BytesIO(create_two_page_pdf("Native first", "Native last")))
    scan = PdfReader(BytesIO(scanned_pdf()))
    blank = PdfReader(BytesIO(create_two_page_pdf("", "")))
    with PdfWriter() as writer, BytesIO() as buffer:
        for page in (native.pages[0], scan.pages[0], blank.pages[0], native.pages[1]):
            writer.add_page(page)
        writer.write(buffer)
        return buffer.getvalue()


def process_result(output: str, code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=output.encode("utf-8"), stderr=b"private path")


class PDFOCRTests(unittest.TestCase):
    def engine(self, text: str = "Tuyển sinh Việt Nam\nEnglish admissions"):
        return patch("rag.ocr.subprocess.run", side_effect=[
            process_result("List of available languages (2):\neng\nvie\n"),
            process_result(text),
        ])

    def test_native_text_never_calls_ocr_or_renderer(self):
        with patch("rag.extraction.ocr_empty_pages") as ocr:
            extracted = extract_content(create_two_page_pdf("Native", "Text"), "application/pdf")
        ocr.assert_not_called()
        self.assertEqual(extracted.text, "Native\n\nText")

    def test_all_scanned_pages_are_ocr_once_in_order(self):
        scan = PdfReader(BytesIO(scanned_pdf()))
        with PdfWriter() as writer, BytesIO() as buffer:
            writer.add_page(scan.pages[0])
            writer.add_page(scan.pages[0])
            writer.write(buffer)
            content = buffer.getvalue()
        with patch("rag.ocr.subprocess.run", side_effect=[
            process_result("eng\nvie"), process_result("Trang một"), process_result("Page two"),
        ]) as run:
            result = extract_content(content, "application/pdf")
        self.assertEqual(result.text, "Trang một\n\nPage two")
        self.assertEqual([s.page_number for s in result.page_spans], [1, 2])
        self.assertEqual(run.call_count, 3)  # one language check per document
        for call in run.call_args_list[1:]:
            self.assertEqual(call.args[0][1:6], ["stdin", "stdout", "-l", "vie+eng", "--dpi"])
            self.assertTrue(call.kwargs["input"].startswith(b"\x89PNG"))
            self.assertEqual(call.kwargs["timeout"], 60)

    def test_mixed_pdf_keeps_native_text_and_original_page_spans(self):
        with self.engine("Trang scan tiếng Việt") as run:
            result = extract_content(mixed_pdf(), "application/pdf")
        self.assertEqual(run.call_count, 2)
        self.assertEqual([s.page_number for s in result.page_spans], [1, 2, 4])
        self.assertEqual(
            [result.text[s.start_offset:s.end_offset] for s in result.page_spans],
            ["Native first", "Trang scan tiếng Việt", "Native last"],
        )

    def test_blank_pdf_skips_engine_and_is_rejected(self):
        with patch("rag.ocr.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "No text could be extracted"):
                extract_content(create_two_page_pdf("", ""), "application/pdf")
        run.assert_not_called()

    def test_nonwhite_scan_with_no_recognized_text_rejects_entire_mixed_pdf(self):
        with self.engine(" \n"), self.assertRaisesRegex(ValueError, "OCR on PDF page 2"):
            extract_content(mixed_pdf(), "application/pdf")

    def test_missing_engine_is_explicit(self):
        with patch("rag.ocr.subprocess.run", side_effect=FileNotFoundError("private path")):
            with self.assertRaisesRegex(OCRUnavailable, "requires Tesseract"):
                extract_content(scanned_pdf(), "application/pdf")

    def test_missing_vietnamese_language_is_explicit(self):
        with patch("rag.ocr.subprocess.run", return_value=process_result("eng")) as run:
            with self.assertRaisesRegex(OCRUnavailable, "both vie and eng"):
                extract_content(scanned_pdf(), "application/pdf")
        self.assertEqual(run.call_count, 1)

    def test_engine_exit_error_is_sanitized(self):
        with patch("rag.ocr.subprocess.run", side_effect=[
            process_result("eng\nvie"), process_result("", 1),
        ]):
            with self.assertRaisesRegex(OCRFailed, "^PDF OCR engine failed$"):
                extract_content(scanned_pdf(), "application/pdf")

    def test_timeout_is_explicit(self):
        with patch("rag.ocr.subprocess.run", side_effect=subprocess.TimeoutExpired("tesseract", 60)):
            with self.assertRaisesRegex(OCRFailed, "timed out"):
                extract_content(scanned_pdf(), "application/pdf")

    def test_missing_renderer_dependency_is_explicit(self):
        with patch.dict(sys.modules, {"pypdfium2": None}):
            with self.assertRaisesRegex(OCRUnavailable, "pypdfium2 and Pillow"):
                extract_content(scanned_pdf(), "application/pdf")

    def test_renderer_failure_is_sanitized(self):
        with patch("pypdfium2.PdfDocument", side_effect=RuntimeError("private path")):
            with self.assertRaisesRegex(OCRFailed, "rendering or decoding failed"):
                extract_content(scanned_pdf(), "application/pdf")

    def test_pdf_temporary_file_cleaned_on_success_and_ocr_failure(self):
        content = scanned_pdf()
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "input.pdf"
                with patch("rag.extraction.NamedTemporaryFile", return_value=path.open("w+b")):
                    if fails:
                        with patch("rag.ocr._run", side_effect=OCRFailed("failed")):
                            with self.assertRaises(OCRFailed):
                                extract_content(content, "application/pdf")
                    else:
                        with self.engine():
                            extract_content(content, "application/pdf")
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_custom_command_and_timeout(self):
        with patch("config.settings", SimpleNamespace(
            rag_tesseract_cmd="C:/OCR/tesseract.exe", rag_ocr_timeout_seconds=12,
        )), self.engine() as run:
            extract_content(scanned_pdf(), "application/pdf")
        self.assertEqual(run.call_args.args[0][0], "C:/OCR/tesseract.exe")
        self.assertEqual(run.call_args.kwargs["timeout"], 12)

    def test_process_start_failure_is_sanitized(self):
        with patch("rag.ocr.subprocess.run", side_effect=PermissionError("private path")):
            with self.assertRaisesRegex(OCRFailed, "could not be started"):
                _run(["tesseract"], 1)

    def test_scanned_pdf_upload_and_url_ocr_before_persisting_chunks(self):
        from fastapi.testclient import TestClient
        from auth import AuthenticatedUser, require_admin
        from main import app
        from rag.url_sources import FetchedSource

        previous = app.dependency_overrides.copy()
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(id=uuid4())
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        client = TestClient(app)
        url = "https://www.vlu.edu.vn/scan.pdf"
        for content, last_page in ((scanned_pdf(), 1), (mixed_pdf(), 4)):
            for is_url in (False, True):
                with self.subTest(is_url=is_url, last_page=last_page):
                    session = Mock()
                    session.scalar.return_value = None
                    document_id = uuid4()

                    def commit():
                        session.add.call_args.args[0].id = document_id

                    session.commit.side_effect = commit
                    with self.engine() as engine, patch(
                        "rag.router.SessionLocal", return_value=session,
                    ), patch(
                        "rag.admin_router.SessionLocal", return_value=session,
                    ), patch("rag.admin_router.fetch_source", return_value=FetchedSource(
                        url=url, filename="scan.pdf", mime_type="application/pdf", content=content,
                    )), patch("rag.ingestion.embed_documents", return_value=[[0.1] * 768]) as embed:
                        if is_url:
                            response = client.post("/admin/knowledge-sources/url", json={"url": url})
                        else:
                            response = client.post("/documents", files={
                                "file": ("scan.pdf", content, "application/pdf"),
                            })
                    self.assertEqual(response.status_code, 201, response.text)
                    document = session.add.call_args.args[0]
                    self.assertEqual(response.json(), {
                        "document_id": str(document_id), "filename": "scan.pdf", "chunk_count": 1,
                    })
                    self.assertEqual(len(document.chunks), 1)
                    chunk = document.chunks[0]
                    self.assertIn("Tuyển sinh Việt Nam", chunk.content)
                    self.assertIn("English admissions", chunk.content)
                    if last_page == 4:
                        self.assertTrue(chunk.content.startswith("Native first\n\n"))
                        self.assertTrue(chunk.content.endswith("\n\nNative last"))
                    self.assertEqual((chunk.page_start, chunk.page_end), (1, last_page))
                    self.assertEqual(document.source_url, url if is_url else None)
                    self.assertEqual(document.source_type, "url" if is_url else "file")
                    self.assertEqual(engine.call_count, 2)
                    self.assertTrue(engine.call_args.kwargs["input"].startswith(b"\x89PNG"))
                    embed.assert_called_once_with([chunk.content])
                    session.add.assert_called_once_with(document)
                    session.commit.assert_called_once_with()

    def test_ocr_failure_stops_before_document_chunks_or_database_writes(self):
        from rag.ingestion import ingest_document
        from rag.ocr import OCRNoText

        cases = (
            (FileNotFoundError("private path"), OCRUnavailable),
            (subprocess.TimeoutExpired("tesseract", 60), OCRFailed),
            ([process_result("eng\nvie"), process_result(" \n")], OCRNoText),
        )
        for process_results, expected in cases:
            with self.subTest(error=expected.__name__):
                session = Mock()
                with patch("rag.ocr.subprocess.run", side_effect=process_results), patch(
                    "rag.ingestion.embed_documents",
                ) as embed, patch("rag.ingestion._build_chunk") as build_chunk, patch(
                    "rag.ingestion.Document",
                ) as document:
                    with self.assertRaises(expected):
                        ingest_document(session, "scan.pdf", "application/pdf", mixed_pdf())
                embed.assert_not_called()
                build_chunk.assert_not_called()
                document.assert_not_called()
                session.add.assert_not_called()
                session.add_all.assert_not_called()
                session.execute.assert_not_called()
                session.flush.assert_not_called()
                session.commit.assert_not_called()

    def test_upload_and_url_endpoints_report_ocr_errors_without_writes(self):
        from fastapi.testclient import TestClient
        from auth import AuthenticatedUser, require_admin
        from main import app
        from rag.ocr import OCRNoText
        from rag.url_sources import FetchedSource

        content = scanned_pdf()
        url = "https://www.vlu.edu.vn/scan.pdf"
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(id=uuid4())
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        client = TestClient(app)
        errors = (
            OCRUnavailable("PDF OCR requires both vie and eng Tesseract language data"),
            OCRFailed("PDF OCR timed out"),
            OCRNoText("No text recognized by OCR on PDF page 1"),
        )
        for is_url in (False, True):
            for error in errors:
                with self.subTest(is_url=is_url, error=type(error).__name__):
                    session = Mock()
                    session.scalar.return_value = None
                    with patch("rag.router.SessionLocal", return_value=session), patch(
                        "rag.admin_router.SessionLocal", return_value=session,
                    ), patch("rag.admin_router.fetch_source", return_value=FetchedSource(
                        url=url, filename="scan.pdf", mime_type="application/pdf", content=content,
                    )), patch("rag.extraction.ocr_empty_pages", side_effect=error), patch(
                        "rag.ingestion.embed_documents",
                    ) as embed:
                        if is_url:
                            response = client.post("/admin/knowledge-sources/url", json={"url": url})
                        else:
                            response = client.post("/documents", files={
                                "file": ("scan.pdf", content, "application/pdf"),
                            })
                    expected = (422 if is_url else 400) if isinstance(error, ValueError) else 503
                    self.assertEqual(response.status_code, expected)
                    self.assertEqual(response.json()["detail"], str(error))
                    embed.assert_not_called()
                    session.add.assert_not_called()
                    session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
