from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from db import Base


class VaultStatus(Base):
    __tablename__ = "vault_status"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=True, index=True, unique=True)
    state = Column(String(20), nullable=False, default="active")
    version = Column(Integer, nullable=False, default=1)
    share_threshold = Column(Integer, nullable=True)
    share_total = Column(Integer, nullable=True)
    grace_started_at = Column(DateTime(timezone=True), nullable=True)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    trigger_reason = Column(String(50), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    vault = relationship("Vault", back_populates="status")