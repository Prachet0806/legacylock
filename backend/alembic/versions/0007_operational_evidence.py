"""Record worker progress and explicitly reported recovery drill evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0007_operational_evidence"
down_revision = "0006_remediation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recovery_ceremony", sa.Column("drill_data", sa.Text(), nullable=True))
    op.create_table(
        "worker_checkpoint",
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(100)),
    )


def downgrade():
    raise RuntimeError("Preserve operational evidence; use a forward repair")
