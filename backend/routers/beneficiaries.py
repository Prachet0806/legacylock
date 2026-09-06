from datetime import UTC, datetime
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models import Beneficiary, User, Vault
from deps import get_db, require_owner
from config import get_settings
from logging_config import log_audit

router = APIRouter(
    prefix="/beneficiaries",
    tags=["beneficiaries"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BeneficiaryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr = Field(..., max_length=320)
    phone: str | None = Field(None, max_length=30)


class BeneficiaryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=30)


class BeneficiaryOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None
    share_index: int | None
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
    vault = db.query(Vault).filter(Vault.user_id == current_user.id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    return vault


def _generate_invitation_hash() -> str:
    """Generate a secure invitation hash."""
    return secrets.token_urlsafe(32)


async def _send_invitation_email(beneficiary: Beneficiary, invitation_link: str) -> None:
    """Send invitation email to beneficiary."""
    from services.notifications import send_email

    await send_email(
        beneficiary.email,
        "LegacyLock — You've Been Invited as a Beneficiary",
        f"""Hello {beneficiary.name},

You have been invited to be a beneficiary for a LegacyLock vault.

To accept this invitation and set up your access, please visit:
{invitation_link}

This invitation will expire in 7 days. If you have any questions, please contact the vault owner directly.

--
LegacyLock
Secure Digital Legacy""",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
def add_beneficiary(data: BeneficiaryCreate, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    
    # Check if beneficiary already exists for this vault
    existing = db.query(Beneficiary).filter(
        Beneficiary.vault_id == vault.id,
        Beneficiary.email == data.email
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Beneficiary with this email already exists")
    
    entry = Beneficiary(
        vault_id=vault.id,
        name=data.name,
        email=str(data.email),
        phone=data.phone,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Beneficiary with this email already exists") from exc
    db.refresh(entry)
    try:
        log_audit("beneficiary.add", "owner", current_user.id, vault.id)
    except Exception:
        pass
    return {"id": entry.id, "message": "Beneficiary added"}


@router.get("", response_model=list[BeneficiaryOut])
def list_beneficiaries(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    rows = db.query(Beneficiary).filter(Beneficiary.vault_id == vault.id).order_by(Beneficiary.created_at.desc()).all()
    return [
        BeneficiaryOut(
            id=r.id,
            name=r.name,
            email=r.email,
            phone=r.phone,
            share_index=r.share_index,
            invitation_status=r.invitation_status,
            invitation_sent_at=r.invitation_sent_at.isoformat() if r.invitation_sent_at else None,
            invitation_accepted_at=r.invitation_accepted_at.isoformat() if r.invitation_accepted_at else None,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.post("/{beneficiary_id}/invite")
async def invite_beneficiary(beneficiary_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """Send invitation email to beneficiary."""
    vault = _get_vault(db, current_user)
    
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.id == beneficiary_id,
        Beneficiary.vault_id == vault.id
    ).first()
    
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    
    # Generate invitation hash if not exists (rotate if expired)
    if not beneficiary.invitation_hash or beneficiary.invitation_status == "expired":
        beneficiary.invitation_hash = _generate_invitation_hash()

    beneficiary.invitation_status = "sent"
    beneficiary.invitation_sent_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        beneficiary.invitation_hash = _generate_invitation_hash()
        db.commit()
    db.refresh(beneficiary)

    # Build invitation link (configurable frontend URL)
    try:
        frontend_url = get_settings().frontend_origin()
    except Exception:
        frontend_url = "http://localhost:3000"
    invitation_link = f"{frontend_url}/access/invite/{beneficiary.invitation_hash}"

    # Send email
    await _send_invitation_email(beneficiary, invitation_link)
    try:
        log_audit("beneficiary.invite", "owner", current_user.id, vault.id)
    except Exception:
        pass
    
    return {
        "message": "Invitation sent",
        "invitation_link": invitation_link,
        "beneficiary_id": beneficiary.id,
    }


@router.put("/{beneficiary_id}")
def update_beneficiary(beneficiary_id: int, data: BeneficiaryUpdate, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.id == beneficiary_id,
        Beneficiary.vault_id == vault.id
    ).first()
    
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    
    if data.name is not None:
        beneficiary.name = data.name
    if data.email is not None:
        beneficiary.email = str(data.email)
    if data.phone is not None:
        beneficiary.phone = data.phone

    beneficiary.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(beneficiary)
    try:
        log_audit("beneficiary.update", "owner", current_user.id, vault.id)
    except Exception:
        pass

    return {"message": "Beneficiary updated"}


@router.delete("/{beneficiary_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_beneficiary(beneficiary_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)

    entry = db.query(Beneficiary).filter(
        Beneficiary.id == beneficiary_id,
        Beneficiary.vault_id == vault.id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Beneficiary not found")

    db.delete(entry)
    db.commit()
    try:
        log_audit("beneficiary.delete", "owner", current_user.id, vault.id)
    except Exception:
        pass