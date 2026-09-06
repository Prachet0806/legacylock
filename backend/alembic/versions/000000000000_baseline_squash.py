"""Baseline squash (all phases, post-hardening).

Revision ID: 000000000000
Revises:
Create Date: 2026-09-06

Squashed prior Phase 1/2 migrations (which had missing heartbeat_config,
missing share_* cols, nullable vault_id drift). DB was wiped per plan, so
no data migration needed. This baseline mirrors current models/ exactly.
"""

from typing import Sequence, Union

from alembic import op

from db import Base
import models  # noqa: F401 - register metadata

# revision identifiers, used by Alembic.
revision: str = "000000000000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
