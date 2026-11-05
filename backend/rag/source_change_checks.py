"""Manual, read-only-to-corpus checks of already indexed URL sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from rag.models import Document, SourceChangeNotification
from rag.url_sources import SourceFetchError, SourceURLValidationError, fetch_source


@dataclass(frozen=True, slots=True)
class CheckResult:
    document_id: UUID
    status: Literal[
        "unchanged", "changed", "already_notified", "unknown_baseline",
        "stale", "fetch_error", "not_url",
    ]


def check_url_source(session: Session, document_id: UUID) -> CheckResult:
    """Compare fetched bytes with the hash stored at ingestion, without reindexing.

    A missing legacy hash cannot establish that a page *changed*. It is
    reported separately and never creates a speculative alert. The second
    locked read prevents a fetch racing with an admin refresh from being
    compared to a different baseline.
    """
    document = session.scalar(select(Document).where(Document.id == document_id))
    if document is None or document.source_type != "url" or not document.source_url:
        session.rollback()
        return CheckResult(document_id, "not_url")
    url, baseline = document.source_url, document.content_hash
    session.rollback()  # Never hold a database transaction during network I/O.
    if baseline is None:
        return CheckResult(document_id, "unknown_baseline")
    try:
        fetched = fetch_source(url)  # Existing host/IP/TLS/redirect/size policy.
    except (SourceFetchError, SourceURLValidationError):
        return CheckResult(document_id, "fetch_error")
    observed = sha256(fetched.content).hexdigest()

    try:
        current = session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if (
            current is None or current.source_type != "url"
            or current.source_url != url or current.content_hash != baseline
        ):
            session.rollback()
            return CheckResult(document_id, "stale")
        current.last_checked_at = datetime.now(timezone.utc)
        if observed == baseline:
            session.commit()
            return CheckResult(document_id, "unchanged")

        statement = insert(SourceChangeNotification).values(
            document_id=document_id, baseline_hash=baseline, observed_hash=observed
        ).on_conflict_do_nothing(
            constraint="uq_source_change_notification_transition"
        )
        inserted = session.execute(statement).rowcount
        session.commit()
        return CheckResult(document_id, "changed" if inserted else "already_notified")
    except Exception:
        session.rollback()
        raise
