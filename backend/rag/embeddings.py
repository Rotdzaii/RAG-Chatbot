import math

from google import genai
from google.genai import types


MODEL = "gemini-embedding-001"
OUTPUT_DIMENSIONALITY = 768


def _get_client() -> genai.Client:
    from config import settings

    if settings.gemini_api_key is None:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings")

    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings")

    return genai.Client(api_key=api_key)


def _normalize_vectors(response: object, expected_count: int) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None)
    if embeddings is None or len(embeddings) != expected_count:
        raise ValueError("Embedding response count mismatch")

    normalized_vectors: list[list[float]] = []
    for embedding in embeddings:
        values = getattr(embedding, "values", None)
        if values is None:
            raise ValueError("Embedding response contains no vector values")

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


def _embed(texts: list[str], task_type: str) -> list[list[float]]:
    client = _get_client()
    try:
        response = client.models.embed_content(
            model=MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=OUTPUT_DIMENSIONALITY,
            ),
        )
        return _normalize_vectors(response, len(texts))
    finally:
        client.close()


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("Document texts must not be blank")

    return _embed(texts, "RETRIEVAL_DOCUMENT")


def embed_query(text: str) -> list[float]:
    if not text.strip():
        raise ValueError("Query text must not be blank")

    return _embed([text], "RETRIEVAL_QUERY")[0]
