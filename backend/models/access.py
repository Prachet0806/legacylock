from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from db import Base


class AccessRequest(Base):
    __tablename__ = "access_request"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    beneficiary_id = Column(Integer, ForeignKey("beneficiary.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    request_reason = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    vault = relationship("Vault", back_populates="access_requests")
    beneficiary = relationship("Beneficiary", back_populates="access_requests")
    approver = relationship("User", back_populates="approved_access_requests")