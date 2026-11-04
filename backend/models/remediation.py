"""Durable recovery, authentication and delivery state. Never stores raw vault secrets."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from db import Base


def now():
    return datetime.now(UTC)


class RecoveryCeremony(Base):
    __tablename__ = "recovery_ceremony"
    id = Column(Integer, primary_key=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=False, index=True)
    generation = Column(String(32), nullable=False)
    threshold = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    expected_revision = Column(Integer, nullable=False)
    initial_material = Column(Text, nullable=True)
    acknowledgments = Column(Text, nullable=True)
    drill_data = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint("vault_id", "generation", name="uq_ceremony_generation"),
        CheckConstraint(
            "status IN ('DRAFT','FINALIZED','CANCELLED','SUPERSEDED')", name="ck_ceremony_status"
        ),
        CheckConstraint(
            "threshold >= 1 AND threshold <= total AND total <= 10", name="ck_ceremony_policy"
        ),
    )


class BusinessEvent(Base):
    __tablename__ = "business_event"
    id = Column(String(36), primary_key=True)
    vault_id = Column(Integer, ForeignKey("vault.id"), nullable=True, index=True)
    kind = Column(String(40), nullable=False)
    revision = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint("vault_id", "kind", "revision", name="uq_business_transition"),
    )


class DeliveryJob(Base):
    __tablename__ = "delivery_job"
    id = Column(String(36), primary_key=True)
    event_id = Column(String(36), ForeignKey("business_event.id"), nullable=False, index=True)
    recipient_key = Column(String(100), nullable=False)
    beneficiary_id = Column(Integer, nullable=True, index=True)  # retain history after deletion
    contact_revision = Column(Integer, nullable=True)
    channel = Column(String(10), nullable=False)
    payload = Column(Text, nullable=True)  # authenticated encryption, separate deployment key
    credential_expires_at = Column(DateTime(timezone=True), nullable=True)
    state = Column(String(20), nullable=False, default="READY", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    due_at = Column(DateTime(timezone=True), nullable=False, default=now, index=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    claim_token = Column(String(36), nullable=True)
    provider_id = Column(String(100), nullable=True)
    last_error = Column(String(100), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint(
            "event_id", "recipient_key", "channel", name="uq_delivery_event_recipient"
        ),
        CheckConstraint(
            "state IN ('READY','CLAIMED','RETRY_WAIT','ACCEPTED','DEAD','CANCELLED')",
            name="ck_delivery_state",
        ),
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempt"
    id = Column(String(36), primary_key=True)  # claim token; no credential content
    job_id = Column(String(36), ForeignKey("delivery_job.id"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    outcome = Column(String(100), nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_session"
    id = Column(String(36), primary_key=True)
    role = Column(String(20), nullable=False)
    principal_id = Column(Integer, nullable=False, index=True)
    vault_id = Column(Integer, nullable=True)
    contact_revision = Column(Integer, nullable=True)
    auth_epoch = Column(String(100), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class SessionRefresh(Base):
    __tablename__ = "session_refresh"
    token_hash = Column(String(64), primary_key=True)
    session_id = Column(String(36), ForeignKey("auth_session.id"), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class AuthChallenge(Base):
    __tablename__ = "auth_challenge"
    token_hash = Column(String(64), primary_key=True)
    beneficiary_id = Column(Integer, nullable=False, index=True)
    contact_revision = Column(Integer, nullable=False)
    purpose = Column(String(30), nullable=False)
    auth_epoch = Column(String(100), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class WorkerCheckpoint(Base):
    __tablename__ = "worker_checkpoint"
    kind = Column(String(20), primary_key=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(100), nullable=True)
