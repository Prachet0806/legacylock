from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from db import Base


class VaultStatus(Base):
    __tablename__ = "vault_status"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True, unique=True)
    state = Column(String(20), nullable=False, default="active")
    version = Column(Integer, nullable=False, default=1)
    # Recovery policy is a versioned crypto constant (Shamir 2-of-3 for v1),
    # not per-row data — see frontend Shamir + KDF_CONTRACTS.
    grace_started_at = Column(DateTime(timezone=True), nullable=True)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    trigger_reason = Column(String(50), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("state IN ('active','grace','triggered')", name="ck_vault_status_state"),
    )

    vault = relationship("Vault", back_populates="status")
