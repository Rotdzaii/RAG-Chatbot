"""add per-document embedding and chunking provenance

Revision ID: b6c8d0e2f4a1
Revises: e7b2c1d4a6f8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c8d0e2f4a1"
down_revision: Union[str, Sequence[str], None] = "e7b2c1d4a6f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing documents remain unknown; their model cannot be proven by schema.
    op.add_column(
        "documents", sa.Column("embedding_profile", sa.String(128), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("chunking_profile", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "chunking_profile")
    op.drop_column("documents", "embedding_profile")
