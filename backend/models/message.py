from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from db import Base


class VaultMessage(Base):
    __tablename__ = "vault_message"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    label = Column(String(200), nullable=False)
    ciphertext = Column(Text, nullable=False)
    wrapped_mek = Column(Text, nullable=False)
    crypto_version = Column(Integer, nullable=False, default=1)
    crypto_metadata = Column(Text, nullable=False)
    # Coverage plumbing only (advisor UI deferred): nullable until set.
    category = Column(String(50), nullable=True)
    coverage_tags = Column(Text, nullable=True)  # JSON-encoded list[str]
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

    vault = relationship("Vault", back_populates="messages")
