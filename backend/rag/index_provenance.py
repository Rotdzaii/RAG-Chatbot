"""Internal IDs for the ingestion configuration that produced a vector.

The IDs describe our configuration, not an immutable provider-side model revision.
Changing extraction/chunking/normalization requires reviewing and bumping the
corresponding ID before ingesting new documents.
"""

from rag.embeddings import MODEL, OUTPUT_DIMENSIONALITY


BASELINE_EMBEDDING_PROFILE = "gemini-embedding-001:768:l2:v1"
CHUNKING_PROFILE = "fixed-character-window:1000:150:v1"


def current_embedding_profile() -> str:
    return f"{MODEL}:{OUTPUT_DIMENSIONALITY}:l2:v1"
