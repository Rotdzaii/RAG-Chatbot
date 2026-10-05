"""add chunk page ranges

Revision ID: e7b2c1d4a6f8
Revises: c4a8b2f91e6d
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b2c1d4a6f8"
down_revision: Union[str, Sequence[str], None] = "c4a8b2f91e6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("page_start", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("page_end", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_chunks_page_range",
        "chunks",
        "(page_start IS NULL AND page_end IS NULL) OR "
        "(page_start IS NOT NULL AND page_end IS NOT NULL AND "
        "page_start >= 1 AND page_end >= page_start)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chunks_page_range", "chunks", type_="check")
    op.drop_column("chunks", "page_end")
    op.drop_column("chunks", "page_start")
