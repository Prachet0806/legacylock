from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from db import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    actor_type = Column(String(20), nullable=False)
    actor_id = Column(Integer, nullable=False)
    event_type = Column(String(50), nullable=False)
    event_metadata = Column(Text, nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )