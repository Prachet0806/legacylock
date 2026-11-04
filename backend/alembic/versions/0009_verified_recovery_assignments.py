"""Clear legacy share-generation claims without ceremony evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0009_verified_recovery"
down_revision = "0008_delivery_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE beneficiary
            SET ceremony_generation = NULL
            WHERE ceremony_generation IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM recovery_ceremony
                  WHERE recovery_ceremony.vault_id = beneficiary.vault_id
                    AND recovery_ceremony.generation = beneficiary.ceremony_generation
                    AND recovery_ceremony.status = 'FINALIZED'
              )
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Do not restore unverified legacy share assignments; use a forward repair")
