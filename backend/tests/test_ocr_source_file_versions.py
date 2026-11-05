"""The two OCR/storage integration cases kept out of the page-OCR PR."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from rag.ocr import OCRFailed
import test_ocr as ocr_tests

mixed_pdf = ocr_tests.mixed_pdf
scanned_pdf = ocr_tests.scanned_pdf


class OCRSourceFileVersionsTests(unittest.TestCase):
    engine = ocr_tests.PDFOCRTests.engine

    def test_file_and_url_pdf_use_one_chunk_set_and_correct_source(self):
        from rag.ingestion import ingest_document

        for url in (None, "https://www.vlu.edu.vn/scan.pdf"):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                session = Mock()
                with self.engine(), patch(
                    "rag.source_files.source_file_directory", return_value=Path(directory),
                ), patch("rag.ingestion.embed_documents", return_value=[[0.1] * 768]) as embed:
                    document = ingest_document(
                        session, "scan.pdf", "application/pdf", mixed_pdf(), source_url=url,
                    )
                self.assertEqual(len(document.chunks), 1)
                self.assertIn("Tuyển sinh Việt Nam", document.chunks[0].content)
                self.assertEqual((document.chunks[0].page_start, document.chunks[0].page_end), (1, 4))
                self.assertEqual(document.source_url, url)
                self.assertEqual(document.source_type, "url" if url else "file")
                self.assertEqual(len(document.file_versions), 0 if url else 1)
                if url is None:
                    self.assertEqual(document.chunks[0].source_file_version_id, document.file_versions[0].id)
                else:
                    self.assertEqual(list(Path(directory).iterdir()), [])
                embed.assert_called_once()
                session.add.assert_called_once_with(document)
                session.commit.assert_called_once()

    def test_ocr_failure_never_embeds_or_writes_database(self):
        from rag.ingestion import ingest_document

        session = Mock()
        with patch("rag.ocr._run", side_effect=OCRFailed("failed")), patch(
            "rag.ingestion.embed_documents",
        ) as embed, patch("rag.ingestion.store_version") as store:
            with self.assertRaises(OCRFailed):
                ingest_document(session, "scan.pdf", "application/pdf", scanned_pdf())
        embed.assert_not_called()
        store.assert_not_called()
        session.add.assert_not_called()
        session.commit.assert_not_called()
