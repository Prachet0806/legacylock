"""Independent session families with atomic single-use refresh history."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from config import get_settings
from models import AuthChallenge, AuthSession, SessionRefresh
from services.auth import create_access_token, hash_token
from services.outbox import cancel_recipient, utc


def issue(db, role, principal_id, vault_id, contact_revision=None):
    settings = get_settings()
    now = datetime.now(UTC)
    family = AuthSession(
        id=str(uuid4()),
        role=role,
        principal_id=principal_id,
        vault_id=vault_id,
        contact_revision=contact_revision,
        auth_epoch=settings.auth_epoch,
        revoked=False,
        expires_at=now + timedelta(days=30 if role == "owner" else 7),
    )
    db.add(family)
    db.flush()
    if role == "beneficiary":
        from models import Beneficiary

        db.get(Beneficiary, principal_id).session_jti = family.id
    return mint(db, family)


def mint(db, family):
    raw = secrets.token_urlsafe(32)
    db.add(
        SessionRefresh(
            token_hash=hash_token(raw), session_id=family.id, expires_at=family.expires_at
        )
    )
    access = create_access_token(
        family.principal_id,
        family.vault_id,
        family.role,
        expires_minutes=15 if family.role == "owner" else 30,
        jti=family.id,
    )
    return access, raw


def valid_family(db, sid, role, principal_id):
    family = db.get(AuthSession, sid)
    if not family or family.revoked or family.role != role or family.principal_id != principal_id:
        return None
    if family.auth_epoch != get_settings().auth_epoch or utc(family.expires_at) <= datetime.now(
        UTC
    ):
        return None
    return family


def rotate(db, raw, role):
    now = datetime.now(UTC)
    if role == "beneficiary":
        candidate = db.get(SessionRefresh, hash_token(raw))
        family = db.get(AuthSession, candidate.session_id) if candidate else None
        if not family or family.role != role:
            raise HTTPException(401, "Invalid or expired session")
        from services.trigger_service import lock_status

        lock_status(db, family.vault_id)
    refresh = (
        db.query(SessionRefresh)
        .filter_by(token_hash=hash_token(raw))
        .populate_existing()
        .with_for_update()
        .first()
    )
    if refresh is None:
        raise HTTPException(401, "Invalid or expired session")
    family = (
        db.query(AuthSession)
        .filter_by(id=refresh.session_id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if not valid_family(db, family.id, role, family.principal_id):
        raise HTTPException(401, "Invalid or expired session")
    if role == "beneficiary":
        from models import Beneficiary

        ben = db.get(Beneficiary, family.principal_id)
        if (
            not ben
            or ben.invitation_status != "accepted"
            or ben.contact_revision != family.contact_revision
        ):
            raise HTTPException(401, "Invalid or expired session")
    if refresh.consumed_at:
        if now - utc(refresh.consumed_at) <= timedelta(seconds=10):
            raise HTTPException(409, "Concurrent refresh; retry using current cookies")
        family.revoked = True
        db.commit()
        raise HTTPException(401, "Refresh reuse detected; sign in again")
    flipped = (
        db.query(SessionRefresh)
        .filter_by(token_hash=refresh.token_hash, consumed_at=None)
        .update({"consumed_at": now}, synchronize_session=False)
    )
    if not flipped:
        raise HTTPException(409, "Concurrent refresh; retry using current cookies")
    return family, mint(db, family)


def revoke_cookie(db, raw, role):
    refresh = db.get(SessionRefresh, hash_token(raw)) if raw else None
    family = db.get(AuthSession, refresh.session_id) if refresh else None
    if family and family.role == role:
        family.revoked = True
        return family
    return None


def revoke_beneficiary(db, ben):
    db.query(AuthSession).filter_by(role="beneficiary", principal_id=ben.id).update(
        {"revoked": True}, synchronize_session=False
    )
    db.query(AuthChallenge).filter_by(beneficiary_id=ben.id, consumed_at=None).update(
        {"consumed_at": datetime.now(UTC)}, synchronize_session=False
    )
    ben.session_jti = ben.refresh_hash = ben.refresh_expires_at = None
    cancel_recipient(db, ben.id)
