"""Add durable recovery, delivery and session state without replacing vault secrets."""

import sqlalchemy as sa

from alembic import op

revision = "0006_remediation"
down_revision = "0005_hardening_constraints"
branch_labels = None
depends_on = None


def dt(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    with op.batch_alter_table("vault") as batch:
        batch.add_column(
            sa.Column("material_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.drop_constraint("ck_vault_recovery_status", type_="check")
        batch.create_check_constraint(
            "ck_vault_recovery_status",
            "recovery_status IN ('READY','DRAFT','LEGACY','UNINITIALIZED')",
        )
    op.execute(
        "UPDATE vault SET recovery_status = CASE WHEN wrapped_vmk IS NULL THEN 'UNINITIALIZED' ELSE 'LEGACY' END, material_revision = CASE WHEN wrapped_vmk IS NULL THEN 0 ELSE 1 END"
    )
    op.add_column(
        "vault_status", sa.Column("armed", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "vault_status", sa.Column("episode", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute(
        "UPDATE vault_status SET armed = true WHERE vault_id IN (SELECT vault_id FROM heartbeat_config WHERE last_check_in IS NOT NULL)"
    )
    op.add_column(
        "beneficiary",
        sa.Column("contact_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("beneficiary", sa.Column("ceremony_generation", sa.String(32), nullable=True))
    op.execute(
        "UPDATE beneficiary SET ceremony_generation = (SELECT recovery_generation FROM vault WHERE vault.id = beneficiary.vault_id)"
    )
    op.create_table(
        "recovery_ceremony",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id"), nullable=False),
        sa.Column("generation", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("initial_material", sa.Text()),
        sa.Column("acknowledgments", sa.Text()),
        dt("created_at", False),
        sa.UniqueConstraint("vault_id", "generation", name="uq_ceremony_generation"),
        sa.CheckConstraint(
            "status IN ('DRAFT','FINALIZED','CANCELLED','SUPERSEDED')", name="ck_ceremony_status"
        ),
        sa.CheckConstraint(
            "threshold >= 1 AND threshold <= total AND total <= 10", name="ck_ceremony_policy"
        ),
    )
    op.create_index("ix_recovery_ceremony_vault_id", "recovery_ceremony", ["vault_id"])
    op.create_table(
        "business_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.Integer(), sa.ForeignKey("vault.id")),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        dt("created_at", False),
        sa.UniqueConstraint("vault_id", "kind", "revision", name="uq_business_transition"),
    )
    op.create_index("ix_business_event_vault_id", "business_event", ["vault_id"])
    op.create_table(
        "delivery_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("business_event.id"), nullable=False),
        sa.Column("recipient_key", sa.String(100), nullable=False),
        sa.Column("beneficiary_id", sa.Integer()),
        sa.Column("contact_revision", sa.Integer()),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("payload", sa.Text()),
        dt("credential_expires_at"),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        dt("due_at", False),
        dt("lease_until"),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("provider_id", sa.String(100)),
        sa.Column("last_error", sa.String(100)),
        dt("accepted_at"),
        dt("created_at", False),
        sa.UniqueConstraint(
            "event_id", "recipient_key", "channel", name="uq_delivery_event_recipient"
        ),
        sa.CheckConstraint(
            "state IN ('READY','CLAIMED','RETRY_WAIT','ACCEPTED','DEAD','CANCELLED')",
            name="ck_delivery_state",
        ),
    )
    for name in ("event_id", "beneficiary_id", "state", "due_at"):
        op.create_index(f"ix_delivery_job_{name}", "delivery_job", [name])
    op.create_table(
        "auth_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("principal_id", sa.Integer(), nullable=False),
        sa.Column("vault_id", sa.Integer()),
        sa.Column("contact_revision", sa.Integer()),
        sa.Column("auth_epoch", sa.String(100), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        dt("expires_at", False),
    )
    op.create_index("ix_auth_session_principal_id", "auth_session", ["principal_id"])
    op.create_table(
        "session_refresh",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("auth_session.id"), nullable=False),
        dt("consumed_at"),
        dt("expires_at", False),
    )
    op.create_index("ix_session_refresh_session_id", "session_refresh", ["session_id"])
    op.create_table(
        "auth_challenge",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("beneficiary_id", sa.Integer(), nullable=False),
        sa.Column("contact_revision", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("auth_epoch", sa.String(100), nullable=False),
        dt("consumed_at"),
        dt("expires_at", False),
        dt("created_at", False),
    )
    op.create_index("ix_auth_challenge_beneficiary_id", "auth_challenge", ["beneficiary_id"])
    op.create_index("ix_vault_message_vault_id_id", "vault_message", ["vault_id", "id"])


def downgrade():
    raise RuntimeError("Use a forward repair: dropping recovery/session/delivery history is unsafe")
