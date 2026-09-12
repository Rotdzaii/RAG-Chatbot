"""enable vector extension

Revision ID: 840cb33bf7b6
Revises: 
Create Date: 2026-09-12 18:17:45.929625

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '840cb33bf7b6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")


def downgrade() -> None:
    """No-op: preserve the pre-existing extension and dependent vector data."""
    pass
