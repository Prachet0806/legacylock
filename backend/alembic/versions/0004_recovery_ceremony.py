"""Recovery ceremony binding (generation id + status).

Revision ID: 0004_recovery_ceremony
Revises: 0003_recovery_policy

- vault.recovery_generation (nullable hex, backfilled NULL = pre-ceremony).
- vault.recovery_status (default READY).
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0004_recovery_ceremony"
down_revision: str = "0003_recovery_policy"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("vault", sa.Column("recovery_generation", sa.String(32), nullable=True))
    op.add_column(
        "vault",
        sa.Column("recovery_status", sa.String(20), nullable=True, server_default="READY"),
    )
    op.execute(sa.text("UPDATE vault SET recovery_status = 'READY' WHERE recovery_status IS NULL"))
    with op.batch_alter_table("vault") as batch:
        batch.alter_column("recovery_status", existing_type=sa.String(20), nullable=False)


def downgrade() -> None:
    op.drop_column("vault", "recovery_status")
    op.drop_column("vault", "recovery_generation")
