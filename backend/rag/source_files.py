"""Private, immutable storage for newly uploaded PDF/TXT source versions."""

from hashlib import sha256
import os
from pathlib import Path
import tempfile
from uuid import UUID

from config import settings


_SUFFIXES = {"application/pdf": ".pdf", "text/plain": ".txt"}
_MAX_FILE_BYTES = 10 * 1024 * 1024


def source_file_directory() -> Path:
    configured = getattr(
        settings, "rag_source_file_dir",
        Path(__file__).resolve().parents[2] / "data" / "source_files",
    )
    return Path(configured).resolve()


def version_path(version_id: UUID, mime_type: str) -> Path:
    # Neither the original filename nor a database-provided path is used here.
    return source_file_directory() / f"{version_id.hex}{_SUFFIXES[mime_type]}"


def store_version(version_id: UUID, mime_type: str, content: bytes) -> None:
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
    version_path(version_id, mime_type).unlink(missing_ok=True)


def read_version(version_id: UUID, mime_type: str, content_hash: str, byte_size: int) -> bytes:
    if not 0 < byte_size <= _MAX_FILE_BYTES:
        raise OSError("Stored source file has invalid size")
    with version_path(version_id, mime_type).open("rb") as handle:
        content = handle.read(byte_size + 1)
    if len(content) != byte_size or sha256(content).hexdigest() != content_hash:
        raise OSError("Stored source file failed integrity check")
    return content
