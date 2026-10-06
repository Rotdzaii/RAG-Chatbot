from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile

from langchain_community.document_loaders import PyPDFLoader
from pypdf.errors import PdfReadError


@dataclass(frozen=True, slots=True)
class PageSpan:
    page_number: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class ExtractedContent:
    text: str
    page_spans: tuple[PageSpan, ...] = ()


class _HTMLTextParser(HTMLParser):
    _ignored = frozenset(
        {"head", "script", "style", "noscript", "svg", "nav", "footer", "form"}
    )
    _blocks = frozenset(
        {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3", "h4", "tr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._ignored:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._blocks:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in self._blocks:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "\n".join(
            line
            for raw_line in "".join(self._parts).splitlines()
            if (line := " ".join(raw_line.split()))
        )


def _extract_pdf_content(content: bytes) -> ExtractedContent:
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

        page_texts = [document.page_content for document in documents]
        raw_text = "\n\n".join(page_texts)
        text_start = len(raw_text) - len(raw_text.lstrip())
        text_end = len(raw_text.rstrip())

        page_spans: list[PageSpan] = []
        offset = 0
        for page_number, page_text in enumerate(page_texts, start=1):
            page_content_start = offset + len(page_text) - len(page_text.lstrip())
            page_content_end = offset + len(page_text.rstrip())
            clipped_start = max(page_content_start, text_start)
            clipped_end = min(page_content_end, text_end)
            if clipped_start < clipped_end:
                page_spans.append(
                    PageSpan(
                        page_number=page_number,
                        start_offset=clipped_start - text_start,
                        end_offset=clipped_end - text_start,
                    )
                )
            offset += len(page_text) + 2

        return ExtractedContent(raw_text[text_start:text_end], tuple(page_spans))
    except PdfReadError as error:
        raise ValueError("Invalid PDF file") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def extract_content(content: bytes, mime_type: str) -> ExtractedContent:
    if mime_type == "application/pdf":
        extracted = _extract_pdf_content(content)
    elif mime_type == "text/plain":
        try:
            extracted = ExtractedContent(content.decode("utf-8-sig").strip())
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 text") from error
    elif mime_type == "text/html":
        try:
            html = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 text") from error
        parser = _HTMLTextParser()
        parser.feed(html)
        extracted = ExtractedContent(parser.text())
    else:
        raise ValueError(f"Unsupported MIME type: {mime_type}")

    if not extracted.text:
        raise ValueError("No text could be extracted")

    return extracted


def extract_text(content: bytes, mime_type: str) -> str:
    return extract_content(content, mime_type).text
