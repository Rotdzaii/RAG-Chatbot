import math

from langchain_google_genai import GoogleGenerativeAIEmbeddings


MODEL = "gemini-embedding-001"
OUTPUT_DIMENSIONALITY = 768


def _get_embeddings() -> GoogleGenerativeAIEmbeddings:
    from config import settings

    if settings.gemini_api_key is None:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings")

    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings")

    return GoogleGenerativeAIEmbeddings(
        model=MODEL,
        api_key=api_key,
        output_dimensionality=OUTPUT_DIMENSIONALITY,
    )


def _normalize_vectors(
    embeddings: list[list[float]] | None, expected_count: int
) -> list[list[float]]:
    if embeddings is None or len(embeddings) != expected_count:
        raise ValueError("Embedding response count mismatch")

    normalized_vectors: list[list[float]] = []
    for values in embeddings:
        vector = [float(value) for value in values]
        if len(vector) != OUTPUT_DIMENSIONALITY:
            raise ValueError(
                f"Embedding vector must have {OUTPUT_DIMENSIONALITY} dimensions"
            )

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise ValueError("Embedding vector must not be zero")

        normalized_vectors.append([value / norm for value in vector])

    return normalized_vectors


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("Document texts must not be blank")

    embeddings = _get_embeddings().embed_documents(texts)
    return _normalize_vectors(embeddings, len(texts))


def embed_query(text: str) -> list[float]:
    if not text.strip():
        raise ValueError("Query text must not be blank")

    embedding = _get_embeddings().embed_query(text)
    return _normalize_vectors([embedding], 1)[0]
