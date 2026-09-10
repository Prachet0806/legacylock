from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from db import Base


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    beneficiary_id = Column(Integer, ForeignKey("beneficiary.id"), nullable=True, index=True)
    channel = Column(String(10), nullable=False)
    notif_type = Column("type", String(30), nullable=False)
    status = Column(String(20), nullable=False)
    provider_message_id = Column(String(100), nullable=True)
    sent_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
