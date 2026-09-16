"""Per-vault Shamir recovery policy (k-of-n).

Revision ID: 0003_recovery_policy
Revises: 0002_email_verification

- vault.recovery_threshold (default 2), vault.recovery_total (default 3).
- Backfills existing rows; legacy vaults stay 2-of-3.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0003_recovery_policy"
down_revision: str = "0002_email_verification"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "vault",
        sa.Column("recovery_threshold", sa.Integer(), nullable=True, server_default="2"),
    )
    op.add_column(
        "vault", sa.Column("recovery_total", sa.Integer(), nullable=True, server_default="3")
    )
    op.execute(sa.text("UPDATE vault SET recovery_threshold = 2 WHERE recovery_threshold IS NULL"))
    op.execute(sa.text("UPDATE vault SET recovery_total = 3 WHERE recovery_total IS NULL"))
    # Enforce NOT NULL after backfill (batch mode not needed for add-column path).
    with op.batch_alter_table("vault") as batch:
        batch.alter_column("recovery_threshold", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("recovery_total", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.drop_column("vault", "recovery_total")
    op.drop_column("vault", "recovery_threshold")
