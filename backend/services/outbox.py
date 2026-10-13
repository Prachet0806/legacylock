"""Transactional delivery intent and a leased, recoverable worker."""

import asyncio
import base64
import hashlib
import json
import random
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import and_, or_

from config import get_settings
from models import Beneficiary, BusinessEvent, DeliveryAttempt, DeliveryJob, VaultStatus


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def payload_key(key_id=None):
    settings = get_settings()
    key_id = key_id or settings.delivery_payload_key_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", key_id):
        raise RuntimeError("Invalid delivery payload key ID")
    encoded = (
        settings.delivery_payload_key
        if key_id == settings.delivery_payload_key_id
        else json.loads(settings.delivery_payload_keys).get(key_id)
    )
    if encoded:
        key = base64.b64decode(encoded, validate=True)
        if len(key) != 32:
            raise RuntimeError("DELIVERY_PAYLOAD_KEY must encode 32 bytes")
        return key
    if settings.environment == "production" or key_id != "v1":
        raise RuntimeError("DELIVERY_PAYLOAD_KEY is required in production")
    return hashlib.sha256(("development-outbox:" + settings.session_secret).encode()).digest()


def context(job, key_id="v1"):
    return f"{key_id}:{job.id}:{job.event_id}:{job.recipient_key}:{job.contact_revision}".encode()


def protect(job, data):
    nonce = secrets.token_bytes(12)
    key_id = get_settings().delivery_payload_key_id
    return (
        key_id
        + ":"
        + base64.b64encode(
            nonce
            + AESGCM(payload_key(key_id)).encrypt(
                nonce, json.dumps(data).encode(), context(job, key_id)
            )
        ).decode()
    )


def unprotect(job):
    if not job.payload or ":" not in job.payload:
        raise ValueError("Unknown payload version")
    key_id, encoded = job.payload.split(":", 1)
    data = base64.b64decode(encoded, validate=True)
    return json.loads(
        AESGCM(payload_key(key_id)).decrypt(data[:12], data[12:], context(job, key_id))
    )


def event(db, vault_id, kind, revision):
    row = BusinessEvent(id=str(uuid4()), vault_id=vault_id, kind=kind, revision=revision)
    db.add(row)
    db.flush()
    return row


def enqueue(
    db,
    business_event,
    recipient_key,
    to,
    subject,
    body,
    *,
    beneficiary=None,
    channel="email",
    expires=None,
):
    job = DeliveryJob(
        id=str(uuid4()),
        event_id=business_event.id,
        recipient_key=recipient_key,
        beneficiary_id=beneficiary.id if beneficiary else None,
        contact_revision=beneficiary.contact_revision if beneficiary else None,
        channel=channel,
        state="READY",
        attempts=0,
        due_at=datetime.now(UTC),
        credential_expires_at=expires,
    )
    job.payload = protect(job, {"to": to, "subject": subject, "body": body})
    db.add(job)
    return job


def cancel_recipient(db, beneficiary_id):
    db.query(DeliveryJob).filter(
        DeliveryJob.beneficiary_id == beneficiary_id,
        DeliveryJob.state.in_(["READY", "RETRY_WAIT", "CLAIMED"]),
    ).update(
        {"state": "CANCELLED", "payload": None, "claim_token": None}, synchronize_session=False
    )


def cancel_warnings(db, vault_id):
    events = db.query(BusinessEvent.id).filter(
        BusinessEvent.vault_id == vault_id, BusinessEvent.kind.like("grace%")
    )
    db.query(DeliveryJob).filter(
        DeliveryJob.event_id.in_(events), DeliveryJob.state.in_(["READY", "RETRY_WAIT", "CLAIMED"])
    ).update(
        {"state": "CANCELLED", "payload": None, "claim_token": None}, synchronize_session=False
    )


def claim(db, now=None, limit=20):
    now = now or datetime.now(UTC)
    due = or_(
        and_(DeliveryJob.state.in_(["READY", "RETRY_WAIT"]), DeliveryJob.due_at <= now),
        and_(DeliveryJob.state == "CLAIMED", DeliveryJob.lease_until <= now),
    )
    permitted = db.query(BusinessEvent.id).filter(
        ~BusinessEvent.kind.like("grace%"), BusinessEvent.kind != "released"
    )
    candidates = (
        db.query(DeliveryJob)
        .filter(due)
        .filter(DeliveryJob.event_id.in_(permitted) if get_settings().release_hold else True)
        .order_by(DeliveryJob.due_at, DeliveryJob.id)
        .with_for_update(skip_locked=True)
        .limit(min(limit, 20))
        .all()
    )
    claimed = []
    for job in candidates:
        token = str(uuid4())
        updated = (
            db.query(DeliveryJob)
            .filter(DeliveryJob.id == job.id, due)
            .update(
                {
                    "state": "CLAIMED",
                    "claim_token": token,
                    "lease_until": now + timedelta(seconds=90),
                    "attempts": DeliveryJob.attempts + 1,
                },
                synchronize_session=False,
            )
        )
        if updated:
            claimed.append((job.id, token))
    db.commit()
    return claimed


async def deliver_one(job_id, token, session_factory):
    from services.notifications import deliver_email, deliver_sms

    db = session_factory()
    try:
        job = (
            db.query(DeliveryJob)
            .filter(
                DeliveryJob.id == job_id,
                DeliveryJob.claim_token == token,
                DeliveryJob.state == "CLAIMED",
            )
            .first()
        )
        if not job:
            return
        business = db.get(BusinessEvent, job.event_id)
        if get_settings().release_hold and (
            business.kind == "released" or business.kind.startswith("grace")
        ):
            job.state, job.claim_token, job.lease_until = "RETRY_WAIT", None, None
            job.due_at = datetime.now(UTC) + timedelta(minutes=1)
            db.commit()
            return
        ben = db.get(Beneficiary, job.beneficiary_id) if job.beneficiary_id else None
        now = datetime.now(UTC)
        if job.attempts > 1 and now - utc(job.created_at) > timedelta(hours=23):
            job.state, job.last_error, job.claim_token = "DEAD", "provider_window_reconcile", None
            db.commit()
            return
        obsolete = job.beneficiary_id and (not ben or ben.contact_revision != job.contact_revision)
        if business.kind.startswith("grace"):
            status = db.query(VaultStatus).filter_by(vault_id=business.vault_id).first()
            obsolete = (
                obsolete
                or not status
                or status.state != "grace"
                or status.episode != business.revision
            )
        if job.credential_expires_at and utc(job.credential_expires_at) <= now:
            obsolete = True
        if obsolete:
            job.state, job.payload, job.claim_token = "CANCELLED", None, None
            db.commit()
            return
        try:
            data = unprotect(job)
        except Exception:
            job.state, job.last_error, job.claim_token = "DEAD", "payload_unavailable", None
            db.commit()
            return
        channel = job.channel
        # A persisted start can remain incomplete after process death or timeout.
        # It means a call was about to start, never proof of inbox delivery.
        db.add(DeliveryAttempt(id=token, job_id=job.id, started_at=datetime.now(UTC)))
        db.commit()  # network I/O runs without a database transaction
        result = await (
            deliver_email(data["to"], data["subject"], data["body"], job_id)
            if channel == "email"
            else deliver_sms(data["to"], data["body"], job_id)
        )
        attempt = db.get(DeliveryAttempt, token)
        if attempt:
            attempt.completed_at, attempt.outcome = (
                datetime.now(UTC),
                result.code or ("accepted" if result.accepted else "provider_unknown"),
            )
        job = (
            db.query(DeliveryJob)
            .filter(
                DeliveryJob.id == job_id,
                DeliveryJob.claim_token == token,
                DeliveryJob.state == "CLAIMED",
            )
            .with_for_update()
            .first()
        )
        if not job:
            db.commit()  # retain this attempt even when another worker reclaimed the job
            return
        job.last_error = result.code
        job.claim_token, job.lease_until = None, None
        if result.accepted:
            job.state, job.accepted_at, job.provider_id, job.payload = (
                "ACCEPTED",
                datetime.now(UTC),
                result.provider_id,
                None,
            )
        elif not result.retryable or job.attempts >= 8:
            job.state = "DEAD"
        else:
            job.state = "RETRY_WAIT"
            job.due_at = datetime.now(UTC) + timedelta(
                seconds=max(
                    result.retry_after or 0, min(3600, 30 * 2**job.attempts) + random.randint(0, 20)
                )
            )
        db.commit()
    finally:
        db.close()


def work_once(session_factory, limit=20):
    if not get_settings().delivery_enabled:
        return 0
    db = session_factory()
    try:
        now = datetime.now(UTC)
        # Bound sensitive-payload cleanup too. Keep terminal outcome evidence.
        expired = (
            db.query(DeliveryJob)
            .filter(
                DeliveryJob.payload.isnot(None),
                or_(
                    DeliveryJob.credential_expires_at <= now,
                    and_(
                        DeliveryJob.state.in_(["DEAD", "CANCELLED", "ACCEPTED"]),
                        DeliveryJob.created_at <= now - timedelta(days=30),
                    ),
                ),
            )
            .order_by(DeliveryJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(100)
            .all()
        )
        for job in expired:
            job.payload = None
            if job.state in ("READY", "RETRY_WAIT", "CLAIMED"):
                job.state, job.claim_token, job.lease_until = "CANCELLED", None, None
        db.commit()
        jobs = claim(db, limit=limit)
    finally:
        db.close()

    async def run():
        semaphore = asyncio.Semaphore(4)

        async def bounded(job_id, token):
            async with semaphore:
                await deliver_one(job_id, token, session_factory)

        await asyncio.gather(*(bounded(*job) for job in jobs))

    asyncio.run(run())
    return len(jobs)
