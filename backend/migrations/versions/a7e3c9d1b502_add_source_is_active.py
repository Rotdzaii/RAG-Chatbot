"""Allow administrators to suspend sources without deleting their index."""
from alembic import op
import sqlalchemy as sa

revision = "a7e3c9d1b502"
down_revision = "c2a1e8d4f6b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("documents", "is_active")
