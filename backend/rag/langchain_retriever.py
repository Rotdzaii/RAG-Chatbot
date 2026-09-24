from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field
from sqlalchemy.orm import Session

from rag.retrieval import retrieve_chunks


class SQLAlchemyVectorRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session: Session
    top_k: int = Field(default=5, ge=1, le=20)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        chunks = retrieve_chunks(self.session, query, top_k=self.top_k)
        return [
            Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": str(chunk.chunk_id),
                    "document_id": str(chunk.document_id),
                    "filename": chunk.filename,
                    "chunk_index": chunk.chunk_index,
                    "cosine_distance": float(chunk.cosine_distance),
                },
            )
            for chunk in chunks
        ]
