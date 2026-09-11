"""Share submission service — idempotent hash intake, per-beneficiary rate-limit.

The browser hashes raw Shamir shares with SHA-256 BEFORE transmission, so raw
share material never crosses the trust boundary. The backend only ever sees,
compares, and stores 64-char hex digests — it cannot verify Shamir correctness
(no VMK server-side) and never reconstructs the VMK (client-only per docs 13).
"""

import re
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import ShareAttempt

MAX_FAILURES = 5
LOCKOUT_MINUTES = 15
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def submit_share(db: Session, vault_id: int, beneficiary_id: int, share_hash: str) -> dict:
    """Record a client-hashed share submission.

    MVP semantics: the server answers "did I receive/store this hash?"
    (accepted/duplicate). Only the browser can answer "do these shares
    reconstruct my VMK?" — via local reconstruction + mismatch reports.
    """
    if not share_hash or not _SHA256_HEX.match(share_hash):
        raise HTTPException(status_code=400, detail="share_hash must be SHA-256 hex")
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

    if attempt and attempt.share_hash == share_hash:
        return {"message": "Share already recorded", "accepted": True, "duplicate": True}

    # New distinct submission: record hash, reset failure window starter.
    # Invalid-vs-valid cannot be decided server-side; counting happens on
    # explicit mismatch reports via `report_mismatch`. For MVP we
    # record the submission idempotently and do not lock honest beneficiaries.
    if not attempt:
        attempt = ShareAttempt(
            vault_id=vault_id, beneficiary_id=beneficiary_id, share_hash=share_hash, failures=0
        )
        db.add(attempt)
    else:
        attempt.share_hash = share_hash
        attempt.failures = 0
        attempt.locked_until = None
        attempt.updated_at = now
    db.commit()
    return {"message": "Share recorded", "accepted": True, "duplicate": False}


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
