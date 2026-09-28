from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from rag.langchain_pipeline import build_rag_pipeline
from rag.retrieval import RetrievedChunk
from rag.tracing import LangChainTraceHandler


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    answer: str
    sources: list[RetrievedChunk]


def answer_question(session: Session, question: str, top_k: int = 5) -> QuestionAnswer:
    from config import settings

    pipeline = build_rag_pipeline(session, top_k=top_k)
    pipeline_input = {"question": question}
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
            content=document.page_content,
            cosine_distance=float(document.metadata["cosine_distance"]),
        )
        for document in result["documents"]
    ]
    return QuestionAnswer(answer=result["answer"], sources=sources)
