"""Preserve actual send-start/completion evidence independently of claim counts."""

import sqlalchemy as sa

from alembic import op

revision = "0008_delivery_attempts"
down_revision = "0007_operational_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "delivery_attempt",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("delivery_job.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(100)),
    )
    op.create_index("ix_delivery_attempt_job_id", "delivery_attempt", ["job_id"])


def downgrade():
    raise RuntimeError("Preserve delivery evidence; use a forward repair")
