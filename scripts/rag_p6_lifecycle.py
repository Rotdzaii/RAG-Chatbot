"""P6 source lifecycle gate with an injectable adapter for offline tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4


class SyntheticEmbeddingFailure(Exception):
    """Injected before DB mutation to check that the previous index survives."""


@dataclass(frozen=True)
class IndexedChunk:
    id: UUID
    content: str
    dimensions: int | None


@dataclass(frozen=True)
class IndexedSource:
    id: UUID
    content_hash: str | None
    embedding_profile: str | None
    chunking_profile: str | None
    chunks: tuple[IndexedChunk, ...]


class LifecycleAdapter(Protocol):
    def create(self, filename: str, content: bytes) -> UUID: ...
    def replace(self, source_id: UUID, filename: str, content: bytes,
                *, fail_embedding: bool = False) -> object: ...
    def inspect(self, source_id: UUID) -> IndexedSource | None: ...
    def delete(self, source_id: UUID) -> bool: ...


def _assert_index(
    indexed: IndexedSource | None, source_id: UUID, content: bytes,
    expected_text: str, embedding_profile: str, chunking_profile: str,
) -> IndexedSource:
    if indexed is None or indexed.id != source_id:
        raise AssertionError("Source is missing after indexing")
    if indexed.content_hash != sha256(content).hexdigest():
        raise AssertionError("Content hash differs from source bytes")
    if indexed.embedding_profile != embedding_profile or indexed.chunking_profile != chunking_profile:
        raise AssertionError("Index profile differs from current configuration")
    if not indexed.chunks or any(chunk.dimensions != 768 for chunk in indexed.chunks):
        raise AssertionError("Source has missing or non-768 embeddings")
    if not any(expected_text in chunk.content for chunk in indexed.chunks):
        raise AssertionError("Expected source content is missing from chunks")
    return indexed


def run_lifecycle_gate(
    adapter: LifecycleAdapter, *, embedding_profile: str, chunking_profile: str,
) -> dict[str, object]:
    """Create only a unique test source and clean it up even on failure."""
    marker = uuid4().hex
    filename = f"rag_p6_gate_{marker}.txt"
    first_text = f"P6 source lifecycle test {marker}: version one."
    second_text = f"P6 source lifecycle test {marker}: version two."
    third_text = f"P6 source lifecycle test {marker}: failed version three."
    first, second, third = (value.encode("utf-8") for value in (
        first_text, second_text, third_text
    ))
    report: dict[str, object] = {
        "schema_version": "1.0", "phase": "P6", "mode": "live_lifecycle_gate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed", "document_id": None, "steps": [],
        "cleanup_status": "not_required", "error_stage": None, "error_type": None,
        "expected_embedding_batches": 2,
        "embedding_profile": embedding_profile,
        "chunking_profile": chunking_profile,
    }
    steps = report["steps"]
    assert isinstance(steps, list)
    source_id: UUID | None = None
    stage = "create"
    try:
        source_id = adapter.create(filename, first)
        report["document_id"] = str(source_id)
        initial = _assert_index(adapter.inspect(source_id), source_id, first, first_text,
                                embedding_profile, chunking_profile)
        steps.append("created_with_valid_index")

        stage = "unchanged"
        unchanged = adapter.replace(source_id, filename, first)
        if getattr(unchanged, "status", None) != "unchanged":
            raise AssertionError("Identical source was not skipped")
        if adapter.inspect(source_id) != initial:
            raise AssertionError("Unchanged source modified its index")
        steps.append("unchanged_index_preserved")

        stage = "replace"
        updated = adapter.replace(source_id, filename, second)
        if getattr(updated, "status", None) != "updated" or getattr(updated, "document_id", None) != source_id:
            raise AssertionError("Changed source was not replaced in place")
        current = _assert_index(adapter.inspect(source_id), source_id, second, second_text,
                                embedding_profile, chunking_profile)
        old_ids = {chunk.id for chunk in initial.chunks}
        if old_ids & {chunk.id for chunk in current.chunks}:
            raise AssertionError("Old chunk IDs remain after replacement")
        if any(first_text in chunk.content for chunk in current.chunks):
            raise AssertionError("Old chunk content remains after replacement")
        steps.append("changed_index_replaced_atomically")

        stage = "embedding_failure"
        try:
            adapter.replace(source_id, filename, third, fail_embedding=True)
        except SyntheticEmbeddingFailure:
            pass
        else:
            raise AssertionError("Fault injection did not stop embedding")
        if adapter.inspect(source_id) != current:
            raise AssertionError("Failed indexing modified the serving source")
        steps.append("failed_embedding_preserved_index")

        stage = "delete"
        if not adapter.delete(source_id) or adapter.inspect(source_id) is not None:
            raise AssertionError("Deletion left a document or chunks")
        source_id = None
        steps.append("document_and_chunks_deleted")
        report["status"] = "passed"
    except Exception as error:
        report["error_stage"] = stage
        report["error_type"] = type(error).__name__
    finally:
        if source_id is not None:
            try:
                adapter.delete(source_id)
                if adapter.inspect(source_id) is not None:
                    raise AssertionError("Test source still exists after cleanup")
                report["cleanup_status"] = "completed"
            except Exception as error:
                report["cleanup_status"] = "failed"
                report["cleanup_error_type"] = type(error).__name__
                report["status"] = "failed"
    return report
