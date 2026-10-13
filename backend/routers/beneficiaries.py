import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_owner
from models import Beneficiary, User, Vault
from services.audit import record_audit
from services.auth import hash_token
from services.sessions import revoke_beneficiary
from services.trigger_service import lock_status

router = APIRouter(
    prefix="/beneficiaries",
    tags=["beneficiaries"],
    dependencies=[Depends(require_owner)],
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

MAX_SHARE_INDEX = 255  # GF(256) x-coord range; per-vault total caps further.

# Accepts the GF(256) range here; routes enforce 1 <= idx <= vault.recovery_total.


class BeneficiaryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr = Field(..., max_length=320)
    phone: str | None = Field(None, max_length=30)
    share_index: int | None = Field(None, ge=1, le=MAX_SHARE_INDEX)


class BeneficiaryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=30)
    share_index: int | None = Field(None, ge=1, le=MAX_SHARE_INDEX)


class BeneficiaryOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None
    share_index: int | None
    assignment_current: bool = False
    invitation_status: str
    invitation_sent_at: str | None
    invitation_accepted_at: str | None
    created_at: str
    model_config = {"from_attributes": True}


class InviteOut(BaseModel):
    beneficiary_id: int
    invitation_link: str
    expires_at: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_vault(db: Session, current_user: User) -> Vault:
    """Get the vault for the current owner."""
    vault = (
        db.query(Vault).filter(Vault.user_id == current_user.id, Vault.is_primary == True).first()
    )
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    return vault


def _policy(vault: Vault) -> tuple[int, int]:
    """Return (threshold, total) with legacy 2-of-3 fallback for old rows."""
    k = getattr(vault, "recovery_threshold", None) or 2
    n = getattr(vault, "recovery_total", None) or 3
    return int(k), int(n)


def _check_share_in_range(vault: Vault, idx: int) -> None:
    _, n = _policy(vault)
    if idx < 1 or idx > n:
        raise HTTPException(status_code=422, detail=f"share_index must be between 1 and {n}")


def _generate_invitation_hash() -> str:
    """Generate a secure invitation token (raw, returned in link)."""
    return secrets.token_urlsafe(32)


def _store_invitation(beneficiary: Beneficiary) -> str:
    """Generate raw invite token, store only its SHA-256 hash. Returns raw for link."""
    raw = secrets.token_urlsafe(32)
    beneficiary.invitation_hash = hash_token(raw)
    return raw


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def add_beneficiary(
    data: BeneficiaryCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    lock_status(db, vault.id)
    db.refresh(vault)
    # Check if beneficiary already exists for this vault
    existing = (
        db.query(Beneficiary)
        .filter(Beneficiary.vault_id == vault.id, Beneficiary.email == data.email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Beneficiary with this email already exists")
    if data.share_index is not None:
        _check_share_in_range(vault, data.share_index)
    entry = Beneficiary(
        vault_id=vault.id,
        name=data.name,
        email=str(data.email),
        phone=data.phone,
        share_index=data.share_index,
    )
    if data.share_index is not None:
        clash = (
            db.query(Beneficiary)
            .filter(
                Beneficiary.vault_id == vault.id,
                Beneficiary.share_index == data.share_index,
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail="share_index already assigned")
    entry.email = entry.email.strip().lower()
    entry.ceremony_generation = vault.recovery_generation if entry.share_index else None
    db.add(entry)
    record_audit(db, vault.id, "owner", current_user.id, "beneficiary.add", {})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Beneficiary with this email already exists"
        ) from exc
    db.refresh(entry)
    return {"id": entry.id, "message": "Beneficiary added"}


@router.get("", response_model=list[BeneficiaryOut])
def list_beneficiaries(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    rows = (
        db.query(Beneficiary)
        .filter(Beneficiary.vault_id == vault.id)
        .order_by(Beneficiary.created_at.desc())
        .all()
    )
    return [
        BeneficiaryOut(
            id=r.id,
            name=r.name,
            email=r.email,
            phone=r.phone,
            share_index=r.share_index,
            assignment_current=bool(
                r.share_index is not None
                and r.ceremony_generation == vault.recovery_generation
                and vault.recovery_status in ("READY", "LEGACY")
            ),
            invitation_status=r.invitation_status,
            invitation_sent_at=r.invitation_sent_at.isoformat() if r.invitation_sent_at else None,
            invitation_accepted_at=r.invitation_accepted_at.isoformat()
            if r.invitation_accepted_at
            else None,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.post("/{beneficiary_id}/invite")
def invite_beneficiary(
    beneficiary_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)
):
    from services.outbox import enqueue, event

    vault = _get_vault(db, current_user)
    revision = lock_status(db, vault.id).version
    db.refresh(vault)
    beneficiary = (
        db.query(Beneficiary)
        .filter_by(id=beneficiary_id, vault_id=vault.id)
        .with_for_update()
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not beneficiary:
        raise HTTPException(404, "Beneficiary not found")
    if beneficiary.invitation_status == "accepted":
        raise HTTPException(409, "Already accepted; beneficiary can request a sign-in link")
    revoke_beneficiary(db, beneficiary)
    raw = _store_invitation(beneficiary)
    beneficiary.invitation_status = "sent"
    beneficiary.invitation_sent_at = datetime.now(UTC)
    invitation_link = f"{get_settings().frontend_origin()}/access/invite#token={raw}"
    business = event(db, vault.id, "invitation", revision)
    enqueue(
        db,
        business,
        f"beneficiary:{beneficiary.id}",
        beneficiary.email,
        "LegacyLock - Beneficiary invitation",
        f"Accept your invitation (expires in 7 days):\n{invitation_link}\nStore your recovery shares separately.",
        beneficiary=beneficiary,
        expires=datetime.now(UTC) + timedelta(days=7),
    )
    record_audit(db, vault.id, "owner", current_user.id, "beneficiary.invite", {})
    db.commit()
    return {
        "message": "Invitation queued",
        "beneficiary_id": beneficiary.id,
        **(
            {"invitation_link": invitation_link}
            if get_settings().environment != "production"
            else {}
        ),
    }


@router.put("/{beneficiary_id}")
def update_beneficiary(
    beneficiary_id: int,
    data: BeneficiaryUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    lock_status(db, vault.id)
    db.refresh(vault)
    beneficiary = (
        db.query(Beneficiary)
        .filter(Beneficiary.id == beneficiary_id, Beneficiary.vault_id == vault.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    if data.name is not None:
        beneficiary.name = data.name
    if data.email is not None and str(data.email).strip().lower() != beneficiary.email:
        revoke_beneficiary(db, beneficiary)
        beneficiary.contact_revision += 1
        beneficiary.email = str(data.email).strip().lower()
        beneficiary.invitation_status = "pending"
        beneficiary.invitation_hash = None
        beneficiary.invitation_accepted_at = None
        beneficiary.invitation_sent_at = None
    if "phone" in data.model_fields_set:
        beneficiary.phone = data.phone
    if "share_index" in data.model_fields_set and data.share_index is None:
        beneficiary.share_index = None
        beneficiary.ceremony_generation = None
    if data.share_index is not None:
        _check_share_in_range(vault, data.share_index)
        clash = (
            db.query(Beneficiary)
            .filter(
                Beneficiary.vault_id == vault.id,
                Beneficiary.share_index == data.share_index,
                Beneficiary.id != beneficiary.id,
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail="share_index already assigned")
        beneficiary.share_index = data.share_index
        beneficiary.ceremony_generation = vault.recovery_generation
    beneficiary.updated_at = datetime.now(UTC)
    record_audit(db, vault.id, "owner", current_user.id, "beneficiary.update", {})
    try:
        db.commit()
    except IntegrityError as exc:
        # Lost a concurrent uniqueness race (email/share_index); the DB
        # constraint is authoritative, the pre-check above is for UX.
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Beneficiary conflicts with an existing record"
        ) from exc
    db.refresh(beneficiary)
    return {"message": "Beneficiary updated"}


class ShareAssignRequest(BaseModel):
    share_index: int = Field(..., ge=1, le=MAX_SHARE_INDEX)


@router.post("/{beneficiary_id}/assign-share")
def assign_share(
    beneficiary_id: int,
    data: ShareAssignRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Assign a Shamir share index (metadata only, never raw share values)."""
    vault = _get_vault(db, current_user)
    lock_status(db, vault.id)
    db.refresh(vault)
    _check_share_in_range(vault, data.share_index)
    beneficiary = (
        db.query(Beneficiary)
        .filter(
            Beneficiary.id == beneficiary_id,
            Beneficiary.vault_id == vault.id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    clash = (
        db.query(Beneficiary)
        .filter(
            Beneficiary.vault_id == vault.id,
            Beneficiary.share_index == data.share_index,
            Beneficiary.id != beneficiary.id,
        )
        .first()
    )
    if clash:
        raise HTTPException(status_code=409, detail="share_index already assigned")
    beneficiary.share_index = data.share_index
    beneficiary.ceremony_generation = vault.recovery_generation
    beneficiary.updated_at = datetime.now(UTC)
    record_audit(db, vault.id, "owner", current_user.id, "beneficiary.update", {})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="share_index already assigned") from exc
    return {"message": "Share index assigned", "share_index": data.share_index}


@router.delete("/{beneficiary_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_beneficiary(
    beneficiary_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)
):
    vault = _get_vault(db, current_user)
    lock_status(db, vault.id)
    db.refresh(vault)
    entry = (
        db.query(Beneficiary)
        .filter(Beneficiary.id == beneficiary_id, Beneficiary.vault_id == vault.id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    revoke_beneficiary(db, entry)
    record_audit(db, vault.id, "owner", current_user.id, "beneficiary.delete", {})
    db.delete(entry)
    db.commit()
