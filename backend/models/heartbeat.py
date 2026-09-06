from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, Integer

from db import Base


class HeartbeatConfig(Base):
    __tablename__ = "heartbeat_config"

    id = Column(Integer, primary_key=True, index=True)
    interval_days = Column(Integer, nullable=False, default=30)
    grace_days = Column(Integer, nullable=False, default=7)
    last_check_in = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )