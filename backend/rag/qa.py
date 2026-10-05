from dataclasses import dataclass
from typing import Literal, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from rag.langchain_pipeline import build_rag_pipeline
from rag.query_contract import HistoryMessage
from rag.query_processing import process_query
from rag.retrieval import RetrievedChunk
from rag.tracing import LangChainTraceHandler


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    answer: str
    sources: list[RetrievedChunk]
    history_used: bool = False
    query_processing_action: Literal["search", "clarify"] = "search"
    query_processing_elapsed_ms: float = 0.0
    rewritten_query: str | None = None


def answer_question(
    session: Session,
    question: str,
    top_k: int = 5,
    *,
    history: Sequence[HistoryMessage] = (),
) -> QuestionAnswer:
    from config import settings

    query_result = process_query(question, history)
    if query_result.action == "clarify":
        if query_result.clarification is None:
            raise ValueError("Clarification result is missing clarification text")
        return QuestionAnswer(
            answer=query_result.clarification,
            sources=[],
            history_used=query_result.history_used,
            query_processing_action="clarify",
            query_processing_elapsed_ms=query_result.elapsed_ms,
            rewritten_query=None,
        )

    if query_result.standalone_query is None:
        raise ValueError("Search result is missing a standalone query")

    pipeline = build_rag_pipeline(session, top_k=top_k)
    pipeline_input = {"question": query_result.standalone_query}
    if getattr(settings, "rag_trace_enabled", False):
        result = pipeline.invoke(
            pipeline_input,
            config={"callbacks": [LangChainTraceHandler()]},
        )
    else:
        result = pipeline.invoke(pipeline_input)
    sources = [
        RetrievedChunk(
            chunk_id=UUID(str(document.metadata["chunk_id"])),
            document_id=UUID(str(document.metadata["document_id"])),
            filename=str(document.metadata["filename"]),
            chunk_index=int(document.metadata["chunk_index"]),
            page_start=(
                int(document.metadata["page_start"])
                if document.metadata.get("page_start") is not None
                else None
            ),
            page_end=(
                int(document.metadata["page_end"])
                if document.metadata.get("page_end") is not None
                else None
            ),
            content=document.page_content,
            cosine_distance=float(document.metadata["cosine_distance"]),
        )
        for document in result["documents"]
    ]
    return QuestionAnswer(
        answer=result["answer"],
        sources=sources,
        history_used=query_result.history_used,
        query_processing_action="search",
        query_processing_elapsed_ms=query_result.elapsed_ms,
        rewritten_query=query_result.standalone_query,
    )
