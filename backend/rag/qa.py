from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from rag.langchain_pipeline import build_rag_pipeline
from rag.retrieval import RetrievedChunk


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    answer: str
    sources: list[RetrievedChunk]


def answer_question(session: Session, question: str, top_k: int = 5) -> QuestionAnswer:
    result = build_rag_pipeline(session, top_k=top_k).invoke({"question": question})
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
