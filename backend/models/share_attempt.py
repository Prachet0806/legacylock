from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from db import Base


class ShareAttempt(Base):
    """Per-beneficiary invalid share counter for rate-limiting (INV-19/20).

    Stores only SHA-256 hashes of submitted shares — never raw share material.
    """

    __tablename__ = "share_attempt"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    beneficiary_id = Column(Integer, ForeignKey("beneficiary.id"), nullable=False, index=True)
    share_hash = Column(String(64), nullable=True)  # sha256 of last submitted share
    failures = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
