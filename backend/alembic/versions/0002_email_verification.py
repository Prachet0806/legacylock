"""Email verification for gated registration (Resend).

Revision ID: 0002_email_verification
Revises: 0001_initial

- user.email_verified_at (nullable; backfilled for pre-existing rows so
  seeded owners are not locked out; new registrations get NULL).
- email_verification_token (hash-only, single-use, expiring).
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0002_email_verification"
down_revision: str = "0001_initial"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    # Grandfather pre-existing (seeded) owners: they proved mailbox control
    # out-of-band; only new registrations must verify.
    op.execute(sa.text("UPDATE \"user\" SET email_verified_at = created_at WHERE email_verified_at IS NULL"))
    op.create_table(
        "email_verification_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("email_verification_token")
    op.drop_column("user", "email_verified_at")
