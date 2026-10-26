"""Durable beneficiary authentication independent of historical invitations."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from config import get_settings
from deps import get_db
from models import AuthChallenge, Beneficiary
from services.audit import record_audit
from services.auth import hash_token
from services.cookies import set_beneficiary_session
from services.outbox import enqueue, event, utc
from services.sessions import issue
from services.trigger_service import lock_status

router = APIRouter(prefix="/access/login", tags=["beneficiary-login"])
_LINK_RESPONSE = (
    "If an accepted beneficiary matches, a sign-in link will be emailed. "
    "If you belong to many vaults, enter the recipient ID from your invitation."
)


class LoginRequest(BaseModel):
    email: EmailStr
    beneficiary_id: int | None = Field(None, ge=1)


class RedeemRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)


@router.post("/request")
def request_link(data: LoginRequest, db=Depends(get_db)):
    now = datetime.now(UTC)
    email = str(data.email).strip().lower()
    query = db.query(Beneficiary).filter_by(email=email, invitation_status="accepted")
    if data.beneficiary_id is not None:
        query = query.filter_by(id=data.beneficiary_id)
    # One durable email-level cooldown prevents a request for an address with
    # many vaults from generating a burst of repeated provider jobs.
    recent = (
        db.query(AuthChallenge.token_hash)
        .join(Beneficiary, AuthChallenge.beneficiary_id == Beneficiary.id)
        .filter(
            Beneficiary.email == email,
            AuthChallenge.purpose == "login",
            AuthChallenge.created_at > now - timedelta(minutes=1),
        )
        .first()
    )
    if recent:
        return {"message": _LINK_RESPONSE}
    candidates = query.order_by(Beneficiary.vault_id, Beneficiary.id).limit(11).all()
    if len(candidates) > 10:
        return {"message": _LINK_RESPONSE}
    for candidate in candidates:
        revision = lock_status(db, candidate.vault_id).version
        ben = (
            db.query(Beneficiary)
            .filter_by(id=candidate.id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if not ben or ben.invitation_status != "accepted" or ben.email != email:
            continue
        latest = (
            db.query(AuthChallenge)
            .filter_by(beneficiary_id=ben.id, purpose="login")
            .order_by(AuthChallenge.created_at.desc())
            .first()
        )
        if latest and now - utc(latest.created_at) < timedelta(minutes=1):
            continue
        raw = secrets.token_urlsafe(32)
        expires = now + timedelta(minutes=15)
        db.add(
            AuthChallenge(
                token_hash=hash_token(raw),
                beneficiary_id=ben.id,
                contact_revision=ben.contact_revision,
                purpose="login",
                auth_epoch=get_settings().auth_epoch,
                expires_at=expires,
                created_at=now,
            )
        )
        business = event(db, ben.vault_id, "beneficiary_login", revision)
        link = f"{get_settings().frontend_origin()}/access/login#token={raw}"
        enqueue(
            db,
            business,
            f"beneficiary:{ben.id}",
            ben.email,
            "LegacyLock — Beneficiary sign-in",
            f"Sign in using this single-use link (expires in 15 minutes):\n{link}\n"
            "You will still need your separately stored recovery shares to "
            "decrypt a released vault.",
            beneficiary=ben,
            expires=expires,
        )
        record_audit(db, ben.vault_id, "beneficiary", ben.id, "auth.challenge_issued", {})
    db.commit()
    return {"message": _LINK_RESPONSE}


@router.post("/redeem")
def redeem_link(data: RedeemRequest, response: Response, db=Depends(get_db)):
    now = datetime.now(UTC)
    row = db.query(AuthChallenge).filter_by(token_hash=hash_token(data.token)).first()
    if (
        not row
        or row.purpose != "login"
        or row.consumed_at
        or utc(row.expires_at) <= now
        or row.auth_epoch != get_settings().auth_epoch
    ):
        raise HTTPException(401, "Invalid or expired sign-in link")
    candidate = db.get(Beneficiary, row.beneficiary_id)
    if not candidate:
        raise HTTPException(401, "Invalid or expired sign-in link")
    lock_status(db, candidate.vault_id)
    ben = (
        db.query(Beneficiary)
        .filter_by(id=row.beneficiary_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if (
        not ben
        or ben.invitation_status != "accepted"
        or ben.contact_revision != row.contact_revision
    ):
        raise HTTPException(401, "Invalid or expired sign-in link")
    db.refresh(row)
    if row.consumed_at:
        raise HTTPException(401, "Invalid or expired sign-in link")
    changed = (
        db.query(AuthChallenge)
        .filter_by(token_hash=row.token_hash, consumed_at=None)
        .update({"consumed_at": now}, synchronize_session=False)
    )
    if not changed:
        raise HTTPException(401, "Invalid or expired sign-in link")
    access, refresh = issue(db, "beneficiary", ben.id, ben.vault_id, ben.contact_revision)
    record_audit(db, ben.vault_id, "beneficiary", ben.id, "auth.login", {})
    db.commit()
    set_beneficiary_session(response, access, refresh)
    return {"message": "Signed in", "beneficiary_id": ben.id}
