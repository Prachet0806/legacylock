"""MVP gaps: message category/tags + share_attempt table.

Revision ID: 000000000001
Revises: 000000000000
"""

import models  # noqa: F401 - register metadata
from alembic import op
from db import Base

revision: str = "000000000001"
down_revision: str | None = "000000000000"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # create_all is idempotent for new tables/columns in dev/test; prod starts from baseline.
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    pass
