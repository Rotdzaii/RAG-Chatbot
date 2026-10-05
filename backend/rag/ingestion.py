from hashlib import sha256

from sqlalchemy.orm import Session

from rag.chunking import TextChunk, chunk_text_with_offsets
from rag.embeddings import embed_documents
from rag.extraction import PageSpan, extract_content
from rag.models import Chunk, Document


def _chunk_page_range(
    chunk: TextChunk, page_spans: tuple[PageSpan, ...]
) -> tuple[int | None, int | None]:
    pages = [
        span.page_number
        for span in page_spans
        if chunk.start_offset < span.end_offset
        and chunk.end_offset > span.start_offset
    ]
    if not pages:
        return None, None
    return pages[0], pages[-1]


def _build_chunk(
    index: int,
    chunk: TextChunk,
    embedding: list[float],
    page_spans: tuple[PageSpan, ...],
) -> Chunk:
    page_start, page_end = _chunk_page_range(chunk, page_spans)
    return Chunk(
        chunk_index=index,
        content=chunk.content,
        embedding=embedding,
        page_start=page_start,
        page_end=page_end,
    )


def ingest_document(
    session: Session, filename: str, mime_type: str, content: bytes
) -> Document:
    if not filename.strip():
        raise ValueError("Filename must not be blank")

    extracted = extract_content(content, mime_type)
    chunks = chunk_text_with_offsets(extracted.text)
    chunk_contents = [chunk.content for chunk in chunks]
    embeddings = embed_documents(chunk_contents)
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk and embedding counts must match")

    document = Document(
        filename=filename,
        mime_type=mime_type,
        content_hash=sha256(content).hexdigest(),
        chunks=[
            _build_chunk(
                index,
                chunk,
                embedding,
                extracted.page_spans,
            )
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ],
    )

    try:
        session.add(document)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return document
