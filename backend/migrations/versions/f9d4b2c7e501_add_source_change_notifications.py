"""Store deduplicated alerts for changed URL source bytes.

Revision ID: f9d4b2c7e501
Revises: b6c8d0e2f4a1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9d4b2c7e501"
down_revision: Union[str, Sequence[str], None] = "b6c8d0e2f4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_change_notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("baseline_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_hash", sa.String(length=64), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "baseline_hash", "observed_hash",
            name="uq_source_change_notification_transition",
        ),
    )
    op.create_index(
        "ix_source_change_notifications_read_at", "source_change_notifications", ["read_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_change_notifications_read_at", table_name="source_change_notifications")
    op.drop_table("source_change_notifications")
