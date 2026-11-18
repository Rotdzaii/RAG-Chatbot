from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from rag.embeddings import embed_query
from rag.index_provenance import BASELINE_EMBEDDING_PROFILE, current_embedding_profile
from rag.models import Chunk, Document
from rag.qa_diagnostics import current_search
from rag.source_metadata import RetrievalFilters


MAX_COSINE_DISTANCE = 0.30


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    content: str
    cosine_distance: float | None
    page_start: int | None = None
    page_end: int | None = None
    source_url: str | None = None
    source_file_version_id: UUID | None = None
    mime_type: str | None = None


def retrieve_chunks(
    session: Session, query: str, top_k: int = 5, *, filters: RetrievalFilters | None = None,
    subject_headers: tuple[UUID, ...] | None = None,
) -> list[RetrievedChunk]:
    return _retrieve(session, query, top_k=top_k, max_distance=MAX_COSINE_DISTANCE,
                     filters=filters, subject_headers=subject_headers)


def retrieve_candidates(
    session: Session, query: str, top_k: int = 20, *, filters: RetrievalFilters | None = None,
) -> list[RetrievedChunk]:
    """Read the nearest candidates for evaluation without a distance cutoff.

    Uses the same embedding and document profile policy as production retrieval.
    This does not change the production retrieval threshold.
    """
    return _retrieve(session, query, top_k=top_k, max_distance=None,
                     **({"filters": filters} if filters is not None else {}))


def active_document_scope(filters: RetrievalFilters | None):
    predicates = [Document.is_active.is_(True)]
    if filters:
        predicates.extend(getattr(Document, key) == value
                          for key, value in filters.model_dump(exclude_none=True).items())
    return predicates


def _retrieve(
    session: Session, query: str, *, top_k: int, max_distance: float | None,
    filters: RetrievalFilters | None = None,
    subject_headers: tuple[UUID, ...] | None = None,
) -> list[RetrievedChunk]:
    if not query.strip():
        raise ValueError("Query must not be blank")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    query_vector = embed_query(query)
    profile = current_embedding_profile()
    compatible_profile = Document.embedding_profile == profile
    if profile == BASELINE_EMBEDDING_PROFILE:
        # Pre-migration documents have unknown provenance. Keep the existing
        # baseline usable, but stop including them if the embedding config changes.
        compatible_profile = or_(
            compatible_profile, Document.embedding_profile.is_(None)
        )
    cosine_distance = Chunk.embedding.cosine_distance(query_vector)
    statement = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id.label("document_id"),
            Document.filename.label("filename"),
            Document.mime_type.label("mime_type"),
            Document.source_url.label("source_url"),
            Chunk.source_file_version_id.label("source_file_version_id"),
            Chunk.chunk_index.label("chunk_index"),
            Chunk.page_start.label("page_start"),
            Chunk.page_end.label("page_end"),
            Chunk.content.label("content"),
            cosine_distance.label("cosine_distance"),
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.embedding.is_not(None))
        .where(*active_document_scope(filters))
        .where(compatible_profile)
    )
    if subject_headers is not None:
        # A replacement gets new chunk IDs. Never attribute its contents to a
        # major identified from a previously read version of the document.
        subject_docs = select(Chunk.document_id).where(Chunk.id.in_(subject_headers))
        statement = statement.where(Document.id.in_(subject_docs))
    scoped = statement
    if max_distance is not None:
        statement = statement.where(cosine_distance <= max_distance)
    statement = statement.order_by(cosine_distance).limit(top_k)

    rows = session.execute(statement).mappings()
    chunks = [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            filename=row["filename"],
            mime_type=row.get("mime_type"),
            source_url=row.get("source_url"),
            source_file_version_id=row.get("source_file_version_id"),
            chunk_index=row["chunk_index"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            content=row["content"],
            cosine_distance=float(row["cosine_distance"]),
        )
        for row in rows
    ]
    observation = current_search.get()
    if observation is not None:
        # Run the normal SELECT first. Examine distances outside both cutoffs
        # with its exact vector, scope and transaction; never feed these rows to QA.
        audit = scoped.with_only_columns(
            Chunk.id.label("chunk_id"), Chunk.document_id, Document.filename,
            Chunk.chunk_index, cosine_distance.label("cosine_distance"),
        ).order_by(cosine_distance, Chunk.id)
        observation.record_candidates(session.execute(audit).mappings(), chunks, max_distance)
    return chunks
