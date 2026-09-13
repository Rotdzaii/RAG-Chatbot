from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.embeddings import embed_query
from rag.models import Chunk, Document


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    content: str
    cosine_distance: float


def retrieve_chunks(
    session: Session, query: str, top_k: int = 5
) -> list[RetrievedChunk]:
    if not query.strip():
        raise ValueError("Query must not be blank")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    query_vector = embed_query(query)
    cosine_distance = Chunk.embedding.cosine_distance(query_vector)
    statement = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id.label("document_id"),
            Document.filename.label("filename"),
            Chunk.chunk_index.label("chunk_index"),
            Chunk.content.label("content"),
            cosine_distance.label("cosine_distance"),
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.embedding.is_not(None))
        .order_by(cosine_distance)
        .limit(top_k)
    )

    rows = session.execute(statement).mappings()
    return [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            filename=row["filename"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            cosine_distance=float(row["cosine_distance"]),
        )
        for row in rows
    ]
