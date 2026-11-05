"""Page-local OCR fallback. Images and recognized text never go to disk."""

from contextlib import closing
from io import BytesIO
import math
from pathlib import Path
import subprocess
from threading import Lock


# PDFium is not thread-safe; FastAPI runs sync uploads in worker threads.
_PDFIUM_LOCK = Lock()


class OCRUnavailable(RuntimeError):
    """The renderer, Tesseract executable or required language data is missing."""


class OCRFailed(RuntimeError):
    """Rendering or recognition failed; do not ingest a partial document."""


class OCRNoText(ValueError):
    """A nonwhite page could not be recognized."""


def _run(command: list[str], timeout: float, content: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            command, input=content, capture_output=True, timeout=timeout,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as error:
        raise OCRUnavailable("PDF OCR requires Tesseract with vie and eng language data") from error
    except subprocess.TimeoutExpired as error:
        raise OCRFailed("PDF OCR timed out") from error
    except OSError as error:
        raise OCRFailed("PDF OCR engine could not be started") from error
    if result.returncode:
        raise OCRFailed("PDF OCR engine failed")
    return result.stdout


def ocr_empty_pages(path: Path, page_texts: list[str]) -> list[str]:
    """Retain native text and page order; OCR only nonblank textless pages.

    A genuinely white page is skipped. A nonwhite page with no recognized text
    rejects the document rather than silently dropping a potentially scanned page.
    """
    try:
        import pypdfium2 as pdfium
        from PIL import Image  # noqa: F401 - required by the PDFium PIL adapter
    except (ImportError, OSError) as error:
        raise OCRUnavailable("PDF OCR requires pypdfium2 and Pillow; sync backend dependencies") from error

    result = list(page_texts)
    ready = False
    try:
        with _PDFIUM_LOCK, pdfium.PdfDocument(path) as pdf:
            if len(pdf) != len(page_texts):
                raise OCRFailed("PDF OCR page count mismatch")
            for index, text in enumerate(page_texts):
                if text.strip():
                    continue
                with closing(pdf[index]) as page:
                    width, height = page.get_size()
                    # Bound memory for oversized pages while targeting 300 DPI.
                    scale = min(300 / 72, math.sqrt(20_000_000 / (width * height)))
                    with closing(page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            if all(low == high == 255 for low, high in image.getextrema()):
                                continue
                            if not ready:
                                from config import settings

                                command = getattr(settings, "rag_tesseract_cmd", "tesseract")
                                timeout = getattr(settings, "rag_ocr_timeout_seconds", 60)
                                if timeout <= 0:
                                    raise OCRUnavailable("PDF OCR timeout must be positive")
                                languages = _run([command, "--list-langs"], timeout).decode("utf-8").splitlines()
                                if not {"vie", "eng"}.issubset({line.strip() for line in languages}):
                                    raise OCRUnavailable("PDF OCR requires both vie and eng Tesseract language data")
                                ready = True
                            with BytesIO() as buffer:
                                image.save(buffer, format="PNG")
                                output = _run(
                                    [command, "stdin", "stdout", "-l", "vie+eng", "--dpi", "300"],
                                    timeout, buffer.getvalue(),
                                )
                            result[index] = output.decode("utf-8").strip()
                            if not result[index]:
                                raise OCRNoText(f"No text recognized by OCR on PDF page {index + 1}")
    except (OCRUnavailable, OCRFailed, OCRNoText):
        raise
    except Exception as error:
        raise OCRFailed("PDF OCR rendering or decoding failed") from error
    return result
