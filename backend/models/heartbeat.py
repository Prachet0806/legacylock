from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from db import Base


class HeartbeatConfig(Base):
    __tablename__ = "heartbeat_config"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, unique=True, index=True)
    interval_days = Column(Integer, nullable=False, default=30)
    grace_days = Column(Integer, nullable=False, default=7)
    last_check_in = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    vault = relationship("Vault", back_populates="heartbeat_config")