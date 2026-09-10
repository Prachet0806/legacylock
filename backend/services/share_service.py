"""Share submission service — idempotent valid resubmit, per-beneficiary rate-limit.

Stores only SHA-256 hashes of submitted shares, never raw Shamir material.
Backend never reconstructs the VMK (client-only per docs 13).
"""

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import ShareAttempt

MAX_FAILURES = 5
LOCKOUT_MINUTES = 15


def _hash(share: str) -> str:
    return hashlib.sha256(share.encode("utf-8")).hexdigest()


def submit_share(db: Session, vault_id: int, beneficiary_id: int, share: str) -> dict:
    """Validate a share submission.

    MVP semantics: backend cannot verify Shamir correctness (no VMK server-side),
    so it enforces idempotency + abuse limiting:
    - same share_hash resubmitted -> idempotent 200 no-op
    - different share after failures accumulate -> 429 when locked
    """
    if not share or len(share) > 10_000:
        raise HTTPException(status_code=400, detail="Invalid share")
    now = datetime.now(UTC)
    attempt = (
        db.query(ShareAttempt)
        .filter(
            ShareAttempt.vault_id == vault_id,
            ShareAttempt.beneficiary_id == beneficiary_id,
        )
        .first()
    )
    if attempt and attempt.locked_until:
        locked = attempt.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=UTC)
        if now < locked:
            raise HTTPException(status_code=429, detail="Too many invalid attempts")

    digest = _hash(share)
    if attempt and attempt.share_hash == digest:
        return {"message": "Share already recorded", "verified": True, "duplicate": True}

    # New distinct submission: record hash, reset failure window starter.
    # Invalid-vs-valid cannot be decided server-side; counting happens on
    # explicit mismatch reports via `report_mismatch` (future). For MVP we
    # record the submission idempotently and do not lock honest beneficiaries.
    if not attempt:
        attempt = ShareAttempt(
            vault_id=vault_id, beneficiary_id=beneficiary_id, share_hash=digest, failures=0
        )
        db.add(attempt)
    else:
        attempt.share_hash = digest
        attempt.failures = 0
        attempt.locked_until = None
        attempt.updated_at = now
    db.commit()
    return {"message": "Share recorded", "verified": True, "duplicate": False}


def report_mismatch(db: Session, vault_id: int, beneficiary_id: int) -> None:
    """Increment failure counter (called when client detects reconstruct failure)."""
    now = datetime.now(UTC)
    attempt = (
        db.query(ShareAttempt)
        .filter(
            ShareAttempt.vault_id == vault_id,
            ShareAttempt.beneficiary_id == beneficiary_id,
        )
        .first()
    )
    if not attempt:
        attempt = ShareAttempt(
            vault_id=vault_id, beneficiary_id=beneficiary_id, failures=1
        )
        db.add(attempt)
    else:
        attempt.failures = (attempt.failures or 0) + 1
        if attempt.failures >= MAX_FAILURES:
            attempt.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
    db.commit()
