from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from db import Base


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    beneficiary_id = Column(Integer, ForeignKey("beneficiary.id"), nullable=True, index=True)
    channel = Column(String(10), nullable=False)
    notif_type = Column("type", String(30), nullable=False)
    # Lifecycle: pending -> sent | failed, gated on the real send result.
    status = Column(String(20), nullable=False)
    provider_message_id = Column(String(100), nullable=True)
    sent_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        # Dedup authority: the pre-check is only a fast path.
        Index(
            "uq_notification_delivery",
            "vault_id",
            "beneficiary_id",
            "type",
            "channel",
            unique=True,
        ),
    )
