"""Remove SMS delivery and phone-number storage.

Revision ID: 0010_email_only_delivery
Revises: 0009_verified_recovery
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_email_only_delivery"
down_revision = "0009_verified_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep historical outcomes while redacting non-email destinations and
    # payloads. Active jobs must never be delivered by the email-only worker.
    op.execute(
        sa.text(
            """
            UPDATE delivery_job
            SET state = CASE
                    WHEN state IN ('READY','CLAIMED','RETRY_WAIT') THEN 'CANCELLED'
                    ELSE state
                END,
                payload = NULL,
                claim_token = NULL,
                lease_until = NULL,
                last_error = CASE
                    WHEN state IN ('READY','CLAIMED','RETRY_WAIT') THEN 'channel_removed'
                    ELSE last_error
                END,
                channel = 'legacy'
            WHERE channel <> 'email'
            """
        )
    )
    with op.batch_alter_table("delivery_job") as batch:
        batch.create_check_constraint("ck_delivery_channel", "channel IN ('email','legacy')")

    # The older notification log is retained for operational history. Relabel
    # its non-email rows without claiming they were emails, and make retries terminal.
    with op.batch_alter_table("notification_log") as batch:
        batch.drop_constraint("ck_notification_channel", type_="check")
    op.execute(
        sa.text(
            """
            UPDATE notification_log
            SET channel = 'legacy',
                status = CASE WHEN status IN ('pending','retrying') THEN 'failed' ELSE status END,
                last_error = CASE
                    WHEN status IN ('pending','retrying') THEN 'channel_removed'
                    ELSE last_error
                END,
                next_retry_at = NULL
            WHERE channel <> 'email'
            """
        )
    )
    with op.batch_alter_table("notification_log") as batch:
        batch.create_check_constraint(
            "ck_notification_channel", "channel IN ('email','legacy')"
        )

    with op.batch_alter_table("beneficiary") as batch:
        batch.drop_column("phone")


def downgrade() -> None:
    raise RuntimeError("Do not restore phone data or non-email delivery; use a forward repair")
