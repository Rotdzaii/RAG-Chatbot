from dataclasses import dataclass

from sqlalchemy.orm import Session

from rag.generation import generate_answer
from rag.retrieval import RetrievedChunk, retrieve_chunks


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    answer: str
    sources: list[RetrievedChunk]


def answer_question(session: Session, question: str, top_k: int = 5) -> QuestionAnswer:
    chunks = retrieve_chunks(session, question, top_k=top_k)
    answer = generate_answer(question, chunks)
    return QuestionAnswer(answer=answer, sources=chunks)
