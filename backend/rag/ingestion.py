from sqlalchemy.orm import Session

from rag.chunking import chunk_text
from rag.embeddings import embed_documents
from rag.extraction import extract_text
from rag.models import Chunk, Document


def ingest_document(
    session: Session, filename: str, mime_type: str, content: bytes
) -> Document:
    if not filename.strip():
        raise ValueError("Filename must not be blank")

    extracted_text = extract_text(content, mime_type)
    chunks = chunk_text(extracted_text)
    embeddings = embed_documents(chunks)
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk and embedding counts must match")

    document = Document(
        filename=filename,
        mime_type=mime_type,
        chunks=[
            Chunk(chunk_index=index, content=chunk, embedding=embedding)
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
