"""Private, immutable storage for newly uploaded PDF/TXT source versions."""

from hashlib import sha256
import logging
import os
from pathlib import Path
import tempfile
from typing import Literal
from uuid import UUID

from config import settings
from rag.supabase_source_storage import get_supabase_source_storage


_SUFFIXES = {"application/pdf": ".pdf", "text/plain": ".txt"}
_MAX_FILE_BYTES = 10 * 1024 * 1024
_Storage = Literal["local", "supabase"]
logger = logging.getLogger(__name__)


def _uses_supabase(storage: _Storage | None = None) -> bool:
    return (storage or getattr(settings, "rag_source_file_storage", "local")) == "supabase"


def _file_key(version_id: UUID, mime_type: str) -> str:
    # Neither the original filename nor a database-provided path is used here.
    return f"{version_id.hex}{_SUFFIXES[mime_type]}"


def source_file_directory() -> Path:
    configured = getattr(
        settings, "rag_source_file_dir",
        Path(__file__).resolve().parents[2] / "data" / "source_files",
    )
    return Path(configured).resolve()


def version_path(version_id: UUID, mime_type: str) -> Path:
    return source_file_directory() / _file_key(version_id, mime_type)


def store_version(
    version_id: UUID, mime_type: str, content: bytes, *, storage: _Storage | None = None,
) -> None:
    if _uses_supabase(storage):
        get_supabase_source_storage().store(_file_key(version_id, mime_type), mime_type, content)
        return

    destination = version_path(version_id, mime_type)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".incoming-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Link is atomic and fails if the immutable destination already exists.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_version(version_id: UUID, mime_type: str) -> None:
    if _uses_supabase():
        get_supabase_source_storage().remove(_file_key(version_id, mime_type))
        return
    version_path(version_id, mime_type).unlink(missing_ok=True)


def cleanup_version(version_id: UUID, mime_type: str) -> None:
    """Try to remove bytes without masking a database error or outcome."""
    try:
        remove_version(version_id, mime_type)
    except OSError:
        logger.warning("Could not remove source file version %s", version_id)


def read_version(
    version_id: UUID, mime_type: str, content_hash: str, byte_size: int,
    *, storage: _Storage | None = None,
) -> bytes:
    if not 0 < byte_size <= _MAX_FILE_BYTES:
        raise OSError("Stored source file has invalid size")
    if _uses_supabase(storage):
        content = get_supabase_source_storage().read(_file_key(version_id, mime_type), byte_size)
    else:
        with version_path(version_id, mime_type).open("rb") as handle:
            content = handle.read(byte_size + 1)
    if len(content) != byte_size or sha256(content).hexdigest() != content_hash:
        raise OSError("Stored source file failed integrity check")
    return content
