from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    content: str
    start_offset: int
    end_offset: int


def chunk_text_with_offsets(
    text: str, chunk_size: int = 1000, overlap: int = 150
) -> list[TextChunk]:
    if not text.strip():
        raise ValueError("Text must not be empty")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be at least 0 and less than chunk_size")

    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        raw_chunk = text[start : start + chunk_size]
        content = raw_chunk.strip()
        if content:
            leading_whitespace = len(raw_chunk) - len(raw_chunk.lstrip())
            chunks.append(
                TextChunk(
                    content=content,
                    start_offset=start + leading_whitespace,
                    end_offset=start + len(raw_chunk.rstrip()),
                )
            )

        end = start + chunk_size
        if end >= len(text):
            break
        start = end - overlap

    return chunks


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    return [
        chunk.content
        for chunk in chunk_text_with_offsets(text, chunk_size, overlap)
    ]
