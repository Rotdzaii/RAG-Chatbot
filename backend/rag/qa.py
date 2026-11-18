from dataclasses import dataclass
import re
from typing import Literal, Sequence
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from rag.citations import cited_source_indices
from rag.langchain_pipeline import build_rag_pipeline
from rag.major_answers import answer_by_major
from rag.major_catalog import MajorCatalog, major_key, read_major_catalog
from rag.qa_diagnostics import QuestionDiagnostics, observe_search
from rag.query_contract import HistoryMessage, MajorQuery, QueryProcessingResult
from rag.query_processing import process_query
from rag.retrieval import RetrievedChunk
from rag.tracing import LangChainTraceHandler
from rag.progress import notify
from rag.source_metadata import RetrievalFilters


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    answer: str
    sources: list[RetrievedChunk]
    history_used: bool = False
    query_processing_action: Literal["search", "clarify"] = "search"
    query_processing_elapsed_ms: float = 0.0
    rewritten_query: str | None = None
    # None keeps compatibility with callers constructing QuestionAnswer directly.
    # Production answers set this to the references actually present in the text.
    cited_source_indices: tuple[int, ...] | None = None


def _clarification(result: QueryProcessingResult, text: str) -> QuestionAnswer:
    notify("validation")
    return QuestionAnswer(
        answer=text, sources=[], history_used=result.history_used,
        query_processing_action="clarify", query_processing_elapsed_ms=result.elapsed_ms,
        cited_source_indices=(),
    )


def _resolve_major_followup(
    catalog: MajorCatalog, question: str, history: Sequence[HistoryMessage], planned: MajorQuery,
) -> MajorQuery | None:
    current = catalog.named_in(question)
    if not current and re.search(r"\bngành (đó|này|ấy)\b", question, re.I):
        previous = next((m.content for m in reversed(history) if m.role == "user"), "")
        names = catalog.named_in(previous)
        if len(names) > 1 or (names and major_key(names[0]) != major_key(planned.major)):
            return None
    if len(current) == 1 and major_key(current[0]) != major_key(planned.major):
        name = current[0]
        switch = rf"^(?:còn|chuyển sang) ngành {re.escape(major_key(name))}(?!\w)"
        match = re.match(switch, major_key(question))
        if match:
            # Keep the facet from the elliptical question, but search the explicitly named program.
            if major_key(question)[match.end():].strip(" ?.!,") and len(question) <= 2000:
                revised = question
            else:
                revised = re.sub(re.escape(planned.major), lambda _: name, planned.question, flags=re.I)
            return MajorQuery(major=name, question=revised)
    return planned


def answer_question(
    session: Session,
    question: str,
    top_k: int = 5,
    *,
    history: Sequence[HistoryMessage] = (),
    filters: RetrievalFilters | None = None,
    diagnostics: QuestionDiagnostics | None = None,
) -> QuestionAnswer:
    from config import settings

    notify("query")
    query_result = process_query(question, history)
    if diagnostics is not None:
        diagnostics.plan = {
            "top_k": top_k, "filters": filters.model_dump(exclude_none=True) if filters else {},
            "action": query_result.action, "scope": query_result.scope,
            "standalone_query": query_result.standalone_query,
            "major_queries": [part.model_dump() for part in query_result.major_queries],
            "comparison_criteria": list(query_result.comparison_criteria),
        }
    if query_result.action == "clarify":
        if query_result.clarification is None:
            raise ValueError("Clarification result is missing clarification text")
        return _clarification(query_result, query_result.clarification)

    standalone = query_result.standalone_query
    if standalone is None:
        raise ValueError("Search result is missing a standalone query")

    config = {"callbacks": [LangChainTraceHandler()]} if getattr(settings, "rag_trace_enabled", False) else None
    parts = query_result.major_queries
    if query_result.scope == "inventory" or parts:
        if len(parts) > top_k:
            return _clarification(query_result, f"Bạn muốn ưu tiên tối đa {top_k} ngành nào trong lượt này?")
        if len({major_key(part.major) for part in parts}) != len(parts):
            return _clarification(query_result, "Bạn muốn hỏi về những ngành nào?")
        notify("retrieval")
        inventory = diagnostics.inventory if diagnostics is not None and query_result.scope == "inventory" else None
        catalog = read_major_catalog(session, filters, inventory=inventory)
        if query_result.scope == "inventory":
            answer, sources = catalog.inventory_answer()
        else:
            if history and len(parts) == 1:
                focus = _resolve_major_followup(catalog, question, history, parts[0])
                if focus is None:
                    return _clarification(query_result, "Bạn muốn hỏi về ngành nào trong các ngành vừa nêu?")
                if focus != parts[0]:
                    parts = (focus,)
                    standalone = f"{focus.major} — {focus.question}"
            criteria = query_result.comparison_criteria or ("Thông tin theo yêu cầu",)
            answer, documents = answer_by_major(
                session, catalog, parts, criteria=criteria if query_result.scope == "compare" else (),
                top_k=top_k, filters=filters, config=config,
                diagnostics=diagnostics,
            )
            sources = _as_sources(documents)
    else:
        pipeline = build_rag_pipeline(
            session, top_k=top_k, **({"filters": filters} if filters is not None else {})
        )
        with observe_search(diagnostics, None, None, standalone, standalone,
                            candidate_limit=top_k, context_budget=top_k) as observation:
            result = pipeline.invoke({"question": standalone}, **({"config": config} if config else {}))
            if observation is not None:
                observation.record_selection({doc.metadata["chunk_id"]: i for i, doc in enumerate(result["documents"], 1)})
        answer = result["answer"]
        sources = _as_sources(result["documents"])
    notify("validation")
    return QuestionAnswer(
        answer=answer, sources=sources, history_used=query_result.history_used,
        query_processing_elapsed_ms=query_result.elapsed_ms, rewritten_query=standalone,
        cited_source_indices=cited_source_indices(answer, len(sources)),
    )


def _as_sources(documents: list[Document]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=UUID(str(document.metadata["chunk_id"])),
            document_id=UUID(str(document.metadata["document_id"])),
            filename=str(document.metadata["filename"]),
            mime_type=document.metadata.get("mime_type"),
            source_url=document.metadata.get("source_url"),
            source_file_version_id=(
                UUID(str(document.metadata["source_file_version_id"]))
                if document.metadata.get("source_file_version_id") is not None else None
            ),
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
        for document in documents
    ]
