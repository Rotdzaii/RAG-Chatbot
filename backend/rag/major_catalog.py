"""Major identities supported by the opening declaration of current source documents."""

from dataclasses import dataclass, field
import re
import unicodedata
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from rag.models import Chunk, Document
from rag.retrieval import RetrievedChunk, active_document_scope
from rag.source_metadata import RetrievalFilters


# Recognize the structured header of a program sheet and the opening definition
# of a VLU program overview. Never scan body text for mentions of other majors.
_HEADER = re.compile(
    r"\A(?:(?:nguồn thử nghiệm:|trang giới thiệu ngành |chương trình đào tạo\b)[^\n]*\n)?"
    r"(?:trường:[^\n]*\n)?(?:tên ngành(?: đào tạo)?|ngành(?: đào tạo)?):[ \t]*(?P<name>[^\n]+)",
    re.IGNORECASE,
)
_OVERVIEW = re.compile(r"\Atổng quan\n(?P<name>[^\n]+?) là ngành học\b", re.IGNORECASE)
_NAME = re.compile(r"[^\W\d_][\w &\-–—()]{0,119}")


def major_key(name: str) -> str:
    name = unicodedata.normalize("NFC", " ".join(name.split())).casefold()
    return re.sub(r"\s*[-–—]\s*", "-", name)


def _identify_subject(content: str) -> tuple[str | None, str]:
    opening = unicodedata.normalize("NFC", content.strip()).replace("\r\n", "\n")
    match = _HEADER.match(opening) or _OVERVIEW.match(opening)
    if match is None:
        return None, "unrecognized_declaration" if opening else "empty_opening_chunk"
    name = match["name"].strip()
    if not _NAME.fullmatch(name) or re.search(r"\b(?:chuyên ngành|ngành)\b", name, re.I):
        return None, "invalid_subject_name"
    if major_key(name) in {"chưa xác định", "chưa cập nhật", "đang cập nhật", "không rõ"}:
        return None, "placeholder_subject"
    # These overviews put a translation in parentheses after the program name.
    if match.re == _OVERVIEW:
        name = re.sub(r" \([^()]+\)$", "", name)
    # A sheet with several subject declarations needs manual disambiguation.
    if re.search(r"^(?:tên ngành(?: đào tạo)?|ngành(?: đào tạo)?):", opening[match.end():], re.I | re.M):
        return None, "multiple_declarations"
    return name, "overview_definition" if match.re == _OVERVIEW else "subject_header"


def subject_name(content: str) -> str | None:
    return _identify_subject(content)[0]


@dataclass
class MajorEvidence:
    name: str
    source: RetrievedChunk
    header_ids: list[UUID] = field(default_factory=list)


@dataclass
class MajorCatalog:
    majors: dict[str, MajorEvidence] = field(default_factory=dict)
    incomplete: bool = False

    def named_in(self, question: str) -> list[str]:
        # Prefer the longest match when one program name contains another.
        if not self.majors:
            return []
        names = "|".join(map(re.escape, sorted(self.majors, key=len, reverse=True)))
        matches = re.findall(rf"(?<!\w)(?:{names})(?!\w)", major_key(question))
        return [self.majors[key].name for key in dict.fromkeys(matches)]

    def inventory_answer(self) -> tuple[str, list[RetrievedChunk]]:
        entries = [self.majors[key] for key in sorted(self.majors)]
        listing = "\n".join(f"- {entry.name} [{i}]" for i, entry in enumerate(entries, 1))
        if self.incomplete:
            answer = "Chưa đủ bằng chứng để chốt tổng số ngành vì còn tài liệu chưa xác định được ngành."
            if entries:
                answer = (
                    f"Đã xác minh {len(entries)} ngành trong kho tài liệu đang sử dụng.\n\n{listing}\n\n"
                    + answer
                )
        elif entries:
            answer = f"Kho tài liệu hiện có thông tin về **{len(entries)} ngành**.\n\n{listing}"
        else:
            answer = "Không có tài liệu đang sử dụng trong phạm vi truy vấn."
        return answer, [entry.source for entry in entries]


def read_major_catalog(session: Session, filters: RetrievalFilters | None, *,
                       inventory: list[dict] | None = None) -> MajorCatalog:
    # Include documents without chunks: silently dropping them would imply a
    # complete inventory. Counting uses text evidence and needs no embeddings.
    statement = (
        select(Document.id, Document.filename, Document.mime_type, Document.source_url,
               Chunk.id.label("chunk_id"), Chunk.content, Chunk.page_start, Chunk.page_end,
               Chunk.source_file_version_id)
        .outerjoin(Chunk, and_(Chunk.document_id == Document.id, Chunk.chunk_index == 0))
        .where(*active_document_scope(filters))
        .order_by(Document.id)
        .execution_options(yield_per=256)
    )
    catalog = MajorCatalog()
    for row in session.execute(statement):
        name, reason = _identify_subject(row.content or "")
        if inventory is not None:
            inventory.append({
                "document_id": str(row.id), "filename": row.filename, "major": name,
                "recognition": reason if row.chunk_id is not None else "missing_opening_chunk",
                "chunk_id": str(row.chunk_id) if row.chunk_id is not None else None,
                "chunk_index": 0 if row.chunk_id is not None else None, "content": row.content,
                "page_start": row.page_start, "page_end": row.page_end,
            })
        if name is None:
            catalog.incomplete = True
            continue
        key = major_key(name)
        if key not in catalog.majors:
            source = RetrievedChunk(
                chunk_id=row.chunk_id, document_id=row.id, filename=row.filename,
                chunk_index=0, content=row.content, cosine_distance=None,
                mime_type=row.mime_type, source_url=row.source_url, title=name,
                source_file_version_id=row.source_file_version_id,
                page_start=row.page_start, page_end=row.page_end,
            )
            catalog.majors[key] = MajorEvidence(name, source)
        catalog.majors[key].header_ids.append(row.chunk_id)
    return catalog
