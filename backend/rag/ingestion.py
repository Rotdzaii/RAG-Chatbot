from hashlib import sha256

from sqlalchemy.orm import Session

from rag.chunking import TextChunk, chunk_text_with_offsets
from rag.embeddings import embed_documents
from rag.extraction import PageSpan, extract_content
from rag.index_provenance import CHUNKING_PROFILE, current_embedding_profile
from rag.models import Chunk, Document


MAX_URL_CHUNKS = 50


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


def _prepare_chunks(
    content: bytes, mime_type: str, *, is_url: bool
) -> tuple[list[TextChunk], tuple[PageSpan, ...], list[list[float]]]:
    extracted = extract_content(content, mime_type)
    chunks = chunk_text_with_offsets(extracted.text)
    if is_url and len(chunks) > MAX_URL_CHUNKS:
        raise ValueError("URL source exceeds 50 chunks")
    embeddings = embed_documents([chunk.content for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise ValueError("Chunk and embedding counts must match")
    return chunks, extracted.page_spans, embeddings


def ingest_document(
    session: Session,
    filename: str,
    mime_type: str,
    content: bytes,
    *,
    source_url: str | None = None,
) -> Document:
    if not filename.strip():
        raise ValueError("Filename must not be blank")

    chunks, page_spans, embeddings = _prepare_chunks(
        content, mime_type, is_url=source_url is not None
    )

    document = Document(
        filename=filename,
        mime_type=mime_type,
        content_hash=sha256(content).hexdigest(),
        source_type="url" if source_url is not None else "file",
        source_url=source_url,
        embedding_profile=current_embedding_profile(),
        chunking_profile=CHUNKING_PROFILE,
        chunks=[
            _build_chunk(
                index,
                chunk,
                embedding,
                page_spans,
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
