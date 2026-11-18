"""Track operational question outcomes and citation provenance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "8d9636d1c45e"
down_revision = "a7e3c9d1b502"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_turns",
        sa.Column("user_id", UUID(), primary_key=True),
        sa.Column("request_id", UUID(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("attempt_id", UUID(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("outcome", sa.String(24)),
        sa.Column("planned_routes", JSONB(), nullable=False),
        sa.Column("executed_routes", JSONB(), nullable=False),
        sa.Column("reasons", JSONB(), nullable=False),
        sa.Column("assistant_message_id", UUID(), sa.ForeignKey("messages.id", ondelete="SET NULL"), unique=True),
        sa.Column("citation_version", sa.Integer()),
        sa.CheckConstraint("state IN ('running', 'completed', 'failed', 'cancelled')", name="ck_question_turns_state"),
        sa.CheckConstraint(
            "(state = 'running' AND finished_at IS NULL AND outcome IS NULL) OR "
            "(state = 'cancelled' AND finished_at IS NOT NULL AND outcome IS NULL) OR "
            "(state = 'completed' AND finished_at IS NOT NULL) OR "
            "(state = 'failed' AND finished_at IS NOT NULL AND outcome IS NOT NULL AND outcome = 'error')",
            name="ck_question_turns_lifecycle",
        ),
        sa.CheckConstraint(
            "outcome IN ('answered', 'partial', 'insufficient_evidence', 'clarification', 'unavailable', 'error')",
            name="ck_question_turns_outcome",
        ),
    )
    op.create_index("ix_question_turns_received_at", "question_turns", ["received_at"])
    # The backend reports only aggregates. No public-role policy exposes rows.
    op.execute("ALTER TABLE question_turns ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("question_turns")
