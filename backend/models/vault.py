from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from db import Base


class Vault(Base):
    __tablename__ = "vault"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    wrapped_vmk = Column(Text, nullable=True)
    vmk_crypto_version = Column(Integer, nullable=True)
    vmk_kdf_algorithm = Column(String(50), nullable=True)
    vmk_kdf_salt = Column(Text, nullable=True)
    vmk_kdf_parameters = Column(Text, nullable=True)
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

    owner = relationship("User", back_populates="vaults")
    messages = relationship("VaultMessage", back_populates="vault", cascade="all, delete-orphan")
    beneficiaries = relationship("Beneficiary", back_populates="vault", cascade="all, delete-orphan")
    status = relationship("VaultStatus", back_populates="vault", cascade="all, delete-orphan", uselist=False)
    access_requests = relationship("AccessRequest", back_populates="vault", cascade="all, delete-orphan")