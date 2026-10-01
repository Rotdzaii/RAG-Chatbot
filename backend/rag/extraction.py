from pathlib import Path
from tempfile import NamedTemporaryFile

from langchain_community.document_loaders import PyPDFLoader
from pypdf.errors import PdfReadError


def _extract_pdf_text(content: bytes) -> str:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(mode="w+b", suffix=".pdf", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)

        documents = PyPDFLoader(
            temporary_path,
            mode="page",
            extract_images=False,
        ).load()
        return "\n\n".join(document.page_content for document in documents)
    except PdfReadError as error:
        raise ValueError("Invalid PDF file") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def extract_text(content: bytes, mime_type: str) -> str:
    if mime_type == "application/pdf":
        extracted_text = _extract_pdf_text(content)
    elif mime_type == "text/plain":
        try:
            extracted_text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 text") from error
    else:
        raise ValueError(f"Unsupported MIME type: {mime_type}")

    extracted_text = extracted_text.strip()
    if not extracted_text:
        raise ValueError("No text could be extracted")

    return extracted_text
