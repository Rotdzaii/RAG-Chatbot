from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    content: str
    start_offset: int
    end_offset: int


def _end_at_word_boundary(
    text: str, start: int, limit: int, chunk_size: int, overlap: int
) -> int:
    """Avoid cutting a word when whitespace is close to the character limit."""
    if limit == len(text) or not (text[limit - 1].isalnum() and text[limit].isalnum()):
        return limit

    search_window = min(80, chunk_size // 10)
    lower = max(start + overlap, limit - search_window)
    for position in range(limit - 1, lower - 1, -1):
        if text[position].isspace():
            return position + 1
    return limit


def _start_at_word_boundary(
    text: str, target: int, previous_start: int, end: int, overlap: int
) -> int:
    """Keep roughly the same overlap while starting at a nearby word boundary."""
    if target == 0 or not (text[target - 1].isalnum() and text[target].isalnum()):
        return target

    radius = min(40, overlap // 2)
    lower = max(previous_start + 1, target - radius)
    upper = min(end - 1, target + radius)
    candidates = [
        position
        for position in range(lower, upper + 1)
        if text[position - 1].isspace()
    ]
    if not candidates:
        return target
    return min(candidates, key=lambda position: (abs(position - target), position))


def chunk_text_with_offsets(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 150,
    *,
    align_to_words: bool = False,
) -> list[TextChunk]:
    """Return source-offset chunks; word alignment is an opt-in offline candidate.

    The ingestion pipeline uses the legacy fixed window until a versioned re-index.
    """
    if not text.strip():
        raise ValueError("Text must not be empty")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be at least 0 and less than chunk_size")

    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if align_to_words:
            end = _end_at_word_boundary(text, start, end, chunk_size, overlap)
        raw_chunk = text[start:end]
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

        if end >= len(text):
            break
        next_start = end - overlap
        if align_to_words:
            next_start = _start_at_word_boundary(text, next_start, start, end, overlap)
        start = next_start if next_start > start else end

    return chunks


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    return [
        chunk.content
        for chunk in chunk_text_with_offsets(text, chunk_size, overlap)
    ]
