"""Extract and validate numbered source references from a generated answer."""

from __future__ import annotations

import re


# Keep the same citation syntax as the chat UI. Exclude Markdown link labels.
_CITATION_GROUP = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\](?!\()")
_SEPARATOR = re.compile(r"\s*[,;]\s*")


def cited_source_indices(answer: str, source_count: int) -> tuple[int, ...]:
    indices: list[int] = []
    seen: set[int] = set()
    for match in _CITATION_GROUP.finditer(answer):
        for part in _SEPARATOR.split(match.group(1)):
            index = int(part)
            if index < 1 or index > source_count:
                raise ValueError("Generated answer references an invalid citation")
            if index not in seen:
                indices.append(index)
                seen.add(index)
    return tuple(indices)
