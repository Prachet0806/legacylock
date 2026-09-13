from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from db import Base


class Beneficiary(Base):
    __tablename__ = "beneficiary"

    id = Column(Integer, primary_key=True, index=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    email = Column(String(320), nullable=False)
    phone = Column(String(30), nullable=True)
    share_index = Column(Integer, nullable=True)
    invitation_hash = Column(Text, nullable=True, unique=True, index=True)
    invitation_status = Column(String(20), nullable=False, default="pending")
    invitation_sent_at = Column(DateTime(timezone=True), nullable=True)
    invitation_accepted_at = Column(DateTime(timezone=True), nullable=True)
    # Beneficiary refresh credential: SHA-256 hash only (raw value lives in
    # an HttpOnly cookie + is rotated on every use). Renews the short-lived
    # access session without depending on a still-valid access JWT.
    refresh_hash = Column(Text, nullable=True, unique=True, index=True)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=True)
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

    __table_args__ = (
        # The DB is the authority on uniqueness; app-level checks give
        # friendlier 409s but cannot close the check-then-insert race.
        UniqueConstraint("vault_id", "email", name="uq_beneficiary_vault_email"),
        Index(
            "uq_beneficiary_vault_share",
            "vault_id",
            "share_index",
            unique=True,
            sqlite_where=(share_index.isnot(None)),
            postgresql_where=(share_index.isnot(None)),
        ),
    )
