"""Add immutable original-file versions for new PDF/TXT citations.

Revision ID: c2a1e8d4f6b0
Revises: f9d4b2c7e501
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2a1e8d4f6b0"
down_revision: Union[str, Sequence[str], None] = "f9d4b2c7e501"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_file_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("chunks", sa.Column("source_file_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_chunks_source_file_version_id", "chunks", "source_file_versions",
        ["source_file_version_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chunks_source_file_version_id", "chunks", type_="foreignkey")
    op.drop_column("chunks", "source_file_version_id")
    op.drop_table("source_file_versions")
