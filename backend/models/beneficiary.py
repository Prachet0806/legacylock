from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from db import Base


class Beneficiary(Base):
    __tablename__ = "beneficiary"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    email = Column(String(320), nullable=False)
    phone = Column(String(30), nullable=True)
    public_key = Column(Text, nullable=True)  # Beneficiary's public key for encrypting shares
    share_index = Column(Integer, nullable=True)
    encrypted_share_data = Column(Text, nullable=True)  # Encrypted share (encrypted with beneficiary's public key)
    invitation_hash = Column(Text, nullable=True, unique=True, index=True)
    invitation_status = Column(String(20), nullable=False, default="pending")
    invitation_sent_at = Column(DateTime(timezone=True), nullable=True)
    invitation_accepted_at = Column(DateTime(timezone=True), nullable=True)
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

    vault = relationship("Vault", back_populates="beneficiaries")
    access_requests = relationship("AccessRequest", back_populates="beneficiary", cascade="all, delete-orphan")