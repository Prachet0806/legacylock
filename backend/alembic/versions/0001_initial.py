"""Initial schema — explicit operations for every table.

Revision ID: 0001_initial
Revises: None (replaces the create_all-based squash; do not mix with it)

This is the single source of truth for schema. Tests run `alembic upgrade
head` against it, so model/migration drift fails loudly instead of hiding
behind create_all().
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def _tz(default_now: bool = True) -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _stamps() -> list:
    return [
        sa.Column("created_at", _tz(), nullable=False),
        sa.Column("updated_at", _tz(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        *_stamps(),
    )
    op.create_table(
        "vault",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("wrapped_vmk", sa.Text(), nullable=True),
        sa.Column("vmk_crypto_version", sa.Integer(), nullable=True),
        sa.Column("vmk_kdf_algorithm", sa.String(50), nullable=True),
        sa.Column("vmk_kdf_salt", sa.Text(), nullable=True),
        sa.Column("vmk_kdf_parameters", sa.Text(), nullable=True),
        *_stamps(),
    )
    op.create_index(
        "uq_vault_primary_per_user",
        "vault",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("is_primary"),
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "vault_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id"), nullable=False, index=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("wrapped_mek", sa.Text(), nullable=False),
        sa.Column("crypto_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("crypto_metadata", sa.Text(), nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("coverage_tags", sa.Text(), nullable=True),
        *_stamps(),
    )
    op.create_table(
        "beneficiary",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("share_index", sa.Integer(), nullable=True),
        sa.Column("invitation_hash", sa.Text(), nullable=True, unique=True, index=True),
        sa.Column("invitation_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("invitation_sent_at", _tz(), nullable=True),
        sa.Column("invitation_accepted_at", _tz(), nullable=True),
        sa.Column("refresh_hash", sa.Text(), nullable=True, unique=True, index=True),
        sa.Column("refresh_expires_at", _tz(), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("vault_id", "email", name="uq_beneficiary_vault_email"),
    )
    op.create_index(
        "uq_beneficiary_vault_share",
        "beneficiary",
        ["vault_id", "share_index"],
        unique=True,
        sqlite_where=sa.text("share_index IS NOT NULL"),
        postgresql_where=sa.text("share_index IS NOT NULL"),
    )
    op.create_table(
        "heartbeat_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vault_id",
            sa.Integer(),
            sa.ForeignKey("vault.id"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("last_check_in", _tz(), nullable=True),
        sa.Column("updated_at", _tz(), nullable=False),
    )
    op.create_table(
        "vault_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vault_id",
            sa.Integer(),
            sa.ForeignKey("vault.id"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("grace_started_at", _tz(), nullable=True),
        sa.Column("triggered_at", _tz(), nullable=True),
        sa.Column("trigger_reason", sa.String(50), nullable=True),
        sa.Column("updated_at", _tz(), nullable=False),
        sa.CheckConstraint("state IN ('active','grace','triggered')", name="ck_vault_status_state"),
    )
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id"), nullable=False, index=True),
        sa.Column(
            "beneficiary_id",
            sa.Integer(),
            sa.ForeignKey("beneficiary.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_message_id", sa.String(100), nullable=True),
        sa.Column("sent_at", _tz(), nullable=False),
        sa.Index(
            "uq_notification_delivery",
            "vault_id",
            "beneficiary_id",
            "type",
            "channel",
            unique=True,
        ),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id"), nullable=True, index=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("event_metadata", sa.Text(), nullable=True),
        sa.Column("timestamp", _tz(), nullable=False),
    )
    op.create_table(
        "refresh_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id"), nullable=True, index=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", sa.String(64), nullable=False, index=True),
        sa.Column("expires_at", _tz(), nullable=False),
        sa.Column("revoked_at", _tz(), nullable=True),
        sa.Column("replaced_by", sa.Integer(), nullable=True),
        sa.Column("created_at", _tz(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "refresh_token",
        "audit_event",
        "notification_log",
        "vault_status",
        "heartbeat_config",
        "beneficiary",
        "vault_message",
        "vault",
        "user",
    ):
        op.drop_table(table)
