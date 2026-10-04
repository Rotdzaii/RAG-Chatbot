"""Canonical RAG corpus snapshot helpers with no database dependencies."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID


SCHEMA_VERSION = "1.0"
EXPECTED_EMBEDDING_DIMENSION = 768


def canonical_payload_bytes(payload: object) -> bytes:
    """Serialize the fingerprinted payload deterministically as UTF-8 JSON."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def payload_fingerprint(payload: object) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def build_snapshot(
    *,
    documents: list[dict[str, object]],
    chunks: list[dict[str, object]],
    pipeline_config: dict[str, object],
    exported_at: str,
) -> dict[str, object]:
    """Build a snapshot whose fingerprint excludes the export timestamp."""
    payload: dict[str, object] = {
        "pipeline_config": pipeline_config,
        "documents": sorted(documents, key=lambda item: str(item["id"])),
        "chunks": sorted(
            chunks,
            key=lambda item: (
                str(item["document_id"]),
                int(item["chunk_index"]),
                str(item["id"]),
            ),
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at,
        "fingerprint_algorithm": "sha256",
        "fingerprint": payload_fingerprint(payload),
        "payload": payload,
    }


def write_snapshot(
    snapshot: dict[str, object], output: Path, *, overwrite: bool = False
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with output.open(mode, encoding="utf-8", newline="\n") as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_snapshot(path: Path) -> object:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def snapshot_summary(snapshot: dict[str, object]) -> dict[str, object]:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Snapshot payload is missing")
    documents = payload.get("documents")
    chunks = payload.get("chunks")
    if not isinstance(documents, list) or not isinstance(chunks, list):
        raise ValueError("Snapshot documents/chunks are missing")

    dimensions: Counter[int] = Counter()
    missing_embeddings = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("embedding_present") is True:
            dimension = chunk.get("embedding_dimension")
            if isinstance(dimension, int) and not isinstance(dimension, bool):
                dimensions[dimension] += 1
        else:
            missing_embeddings += 1

    return {
        "documents": len(documents),
        "chunks": len(chunks),
        "embedding_dimensions": dict(sorted(dimensions.items())),
        "missing_embeddings": missing_embeddings,
        "fingerprint": snapshot.get("fingerprint"),
    }


def validate_snapshot(snapshot: object) -> list[str]:
    """Return all offline schema, integrity, and embedding errors."""
    errors: list[str] = []
    if not isinstance(snapshot, dict):
        return ["snapshot must be a JSON object"]

    _require_keys(
        snapshot,
        {
            "schema_version",
            "exported_at",
            "fingerprint_algorithm",
            "fingerprint",
            "payload",
        },
        "snapshot",
        errors,
    )
    _reject_unknown_keys(
        snapshot,
        {
            "schema_version",
            "exported_at",
            "fingerprint_algorithm",
            "fingerprint",
            "payload",
        },
        "snapshot",
        errors,
    )

    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if not isinstance(snapshot.get("exported_at"), str) or not snapshot.get(
        "exported_at"
    ):
        errors.append("exported_at must be a non-empty string")
    if snapshot.get("fingerprint_algorithm") != "sha256":
        errors.append("fingerprint_algorithm must be 'sha256'")

    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        errors.append("payload must be an object")
        return errors
    _require_keys(
        payload,
        {"pipeline_config", "documents", "chunks"},
        "payload",
        errors,
    )
    _reject_unknown_keys(
        payload,
        {"pipeline_config", "documents", "chunks"},
        "payload",
        errors,
    )

    fingerprint = snapshot.get("fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        errors.append("fingerprint must be a 64-character SHA-256 hex string")
    else:
        try:
            int(fingerprint, 16)
        except ValueError:
            errors.append("fingerprint must contain hexadecimal characters only")
        else:
            actual = payload_fingerprint(payload)
            if fingerprint != actual:
                errors.append(
                    f"fingerprint mismatch: expected {fingerprint}, computed {actual}"
                )

    pipeline_config = payload.get("pipeline_config")
    if not isinstance(pipeline_config, dict):
        errors.append("payload.pipeline_config must be an object")
    else:
        _require_keys(
            pipeline_config,
            {
                "extraction",
                "chunking",
                "embedding",
                "query_processing",
                "retrieval",
                "generation",
            },
            "payload.pipeline_config",
            errors,
        )
    documents = payload.get("documents")
    chunks = payload.get("chunks")
    if not isinstance(documents, list):
        errors.append("payload.documents must be an array")
        documents = []
    if not isinstance(chunks, list):
        errors.append("payload.chunks must be an array")
        chunks = []

    document_ids: set[str] = set()
    for index, document in enumerate(documents):
        prefix = f"documents[{index}]"
        if not isinstance(document, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _require_keys(
            document,
            {
                "id",
                "filename",
                "mime_type",
                "source_type",
                "source_url",
                "category",
                "audience",
                "content_hash",
                "published_at",
                "last_checked_at",
                "effective_from",
                "effective_to",
                "created_at",
                "updated_at",
            },
            prefix,
            errors,
        )
        _reject_unknown_keys(
            document,
            {
                "id",
                "filename",
                "mime_type",
                "source_type",
                "source_url",
                "category",
                "audience",
                "content_hash",
                "published_at",
                "last_checked_at",
                "effective_from",
                "effective_to",
                "created_at",
                "updated_at",
            },
            prefix,
            errors,
        )
        document_id = _non_empty_string(document.get("id"))
        if document_id is None:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif not _is_uuid(document_id):
            errors.append(f"{prefix}.id must be a UUID")
        elif document_id in document_ids:
            errors.append(f"duplicate document id: {document_id}")
        else:
            document_ids.add(document_id)
        for field in ("filename", "mime_type", "source_type"):
            if _non_empty_string(document.get(field)) is None:
                errors.append(f"{prefix}.{field} must be a non-empty string")
        for field in (
            "source_url",
            "category",
            "audience",
            "content_hash",
            "published_at",
            "last_checked_at",
            "effective_from",
            "effective_to",
        ):
            value = document.get(field)
            if value is not None and not isinstance(value, str):
                errors.append(f"{prefix}.{field} must be a string or null")
        for field in ("created_at", "updated_at"):
            if _non_empty_string(document.get(field)) is None:
                errors.append(f"{prefix}.{field} must be a non-empty string")

    chunk_ids: set[str] = set()
    document_chunk_indexes: set[tuple[str, int]] = set()
    for index, chunk in enumerate(chunks):
        prefix = f"chunks[{index}]"
        if not isinstance(chunk, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _require_keys(
            chunk,
            {
                "id",
                "document_id",
                "chunk_index",
                "content",
                "embedding_present",
                "embedding_dimension",
                "created_at",
            },
            prefix,
            errors,
        )
        _reject_unknown_keys(
            chunk,
            {
                "id",
                "document_id",
                "chunk_index",
                "content",
                "embedding_present",
                "embedding_dimension",
                "created_at",
            },
            prefix,
            errors,
        )

        chunk_id = _non_empty_string(chunk.get("id"))
        if chunk_id is None:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif not _is_uuid(chunk_id):
            errors.append(f"{prefix}.id must be a UUID")
        elif chunk_id in chunk_ids:
            errors.append(f"duplicate chunk id: {chunk_id}")
        else:
            chunk_ids.add(chunk_id)

        document_id = _non_empty_string(chunk.get("document_id"))
        if document_id is None:
            errors.append(f"{prefix}.document_id must be a non-empty string")
        elif not _is_uuid(document_id):
            errors.append(f"{prefix}.document_id must be a UUID")
        elif document_id not in document_ids:
            errors.append(f"orphan chunk {chunk_id or index}: document {document_id} missing")

        chunk_index = chunk.get("chunk_index")
        if (
            not isinstance(chunk_index, int)
            or isinstance(chunk_index, bool)
            or chunk_index < 0
        ):
            errors.append(f"{prefix}.chunk_index must be a non-negative integer")
        elif document_id is not None:
            key = (document_id, chunk_index)
            if key in document_chunk_indexes:
                errors.append(
                    f"duplicate chunk_index {chunk_index} for document {document_id}"
                )
            else:
                document_chunk_indexes.add(key)

        content = chunk.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{prefix}.content must be a non-empty string")
        if _non_empty_string(chunk.get("created_at")) is None:
            errors.append(f"{prefix}.created_at must be a non-empty string")

        present = chunk.get("embedding_present")
        dimension = chunk.get("embedding_dimension")
        if not isinstance(present, bool):
            errors.append(f"{prefix}.embedding_present must be a boolean")
        elif not present:
            errors.append(f"{prefix}.embedding is missing")
            if dimension is not None:
                errors.append(
                    f"{prefix}.embedding_dimension must be null when embedding is missing"
                )
        elif (
            not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension != EXPECTED_EMBEDDING_DIMENSION
        ):
            errors.append(
                f"{prefix}.embedding_dimension must be "
                f"{EXPECTED_EMBEDDING_DIMENSION} when embedding is present"
            )

    return errors


def _non_empty_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _require_keys(
    value: dict[str, object],
    required: set[str],
    prefix: str,
    errors: list[str],
) -> None:
    for key in sorted(required - value.keys()):
        errors.append(f"{prefix}.{key} is required")


def _reject_unknown_keys(
    value: dict[str, object],
    allowed: set[str],
    prefix: str,
    errors: list[str],
) -> None:
    for key in sorted(value.keys() - allowed):
        errors.append(f"{prefix}.{key} is not allowed")
