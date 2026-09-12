from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_text(content: bytes, mime_type: str) -> str:
    if mime_type == "application/pdf":
        try:
            extracted_text = "\n\n".join(
                page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages
            )
        except PdfReadError as error:
            raise ValueError("Invalid PDF file") from error
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
