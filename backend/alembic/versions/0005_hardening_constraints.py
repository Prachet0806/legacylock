"""Phase B hardening: lifecycle CHECK domains + durability/correlation columns.

Revision ID: 0005_hardening_constraints
Revises: 0004_recovery_ceremony

- vault: recovery range CHECK (1<=k<=n<=10), recovery_status domain CHECK.
- beneficiary: invitation_status domain CHECK, share_index 1..255 CHECK,
  new session_jti (nullable, indexed) for server-side JWT revocation.
- notification_log: status/channel domain CHECKs, attempts/last_error/
  next_retry_at durability columns.
- audit_event: request_id + ip_address correlation columns (nullable).
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0005_hardening_constraints"
down_revision: str = "0004_recovery_ceremony"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    # SQLite cannot ALTER constraints outside batch (copy-and-move) mode;
    # batch works on both SQLite and Postgres, so use it everywhere.
    with op.batch_alter_table("vault") as batch:
        batch.create_check_constraint(
            "ck_vault_recovery_range",
            "recovery_threshold >= 1 AND recovery_threshold <= recovery_total "
            "AND recovery_total >= 1 AND recovery_total <= 10",
        )
        batch.create_check_constraint(
            "ck_vault_recovery_status",
            "recovery_status IN ('READY')",
        )
    with op.batch_alter_table("beneficiary") as batch:
        batch.create_check_constraint(
            "ck_beneficiary_invite_status",
            "invitation_status IN ('pending','sent','accepted','expired')",
        )
        batch.create_check_constraint(
            "ck_beneficiary_share_range",
            "share_index IS NULL OR (share_index >= 1 AND share_index <= 255)",
        )
    op.add_column("beneficiary", sa.Column("session_jti", sa.String(64), nullable=True))
    op.create_index("ix_beneficiary_session_jti", "beneficiary", ["session_jti"])

    with op.batch_alter_table("notification_log") as batch:
        batch.create_check_constraint(
            "ck_notification_status",
            "status IN ('pending','sent','failed','retrying')",
        )
        batch.create_check_constraint(
            "ck_notification_channel",
            "channel IN ('email','sms')",
        )
    op.add_column(
        "notification_log",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("notification_log", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "notification_log", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column("audit_event", sa.Column("request_id", sa.String(32), nullable=True))
    op.add_column("audit_event", sa.Column("ip_address", sa.String(64), nullable=True))
    op.create_index("ix_audit_event_request_id", "audit_event", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_request_id", table_name="audit_event")
    op.drop_column("audit_event", "ip_address")
    op.drop_column("audit_event", "request_id")
    op.drop_column("notification_log", "next_retry_at")
    op.drop_column("notification_log", "last_error")
    op.drop_column("notification_log", "attempts")
    with op.batch_alter_table("notification_log") as batch:
        batch.drop_constraint("ck_notification_channel", type_="check")
        batch.drop_constraint("ck_notification_status", type_="check")
    op.drop_index("ix_beneficiary_session_jti", table_name="beneficiary")
    op.drop_column("beneficiary", "session_jti")
    with op.batch_alter_table("beneficiary") as batch:
        batch.drop_constraint("ck_beneficiary_share_range", type_="check")
        batch.drop_constraint("ck_beneficiary_invite_status", type_="check")
    with op.batch_alter_table("vault") as batch:
        batch.drop_constraint("ck_vault_recovery_status", type_="check")
        batch.drop_constraint("ck_vault_recovery_range", type_="check")
