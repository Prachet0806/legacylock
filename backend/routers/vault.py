import base64
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from deps import get_db, require_owner
from logging_config import log_audit
from models import User, Vault, VaultMessage
from services.auth import verify_password

router = APIRouter(
    prefix="/vault",
    tags=["vault"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MessageRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    encrypted_content: str | None = Field(None, max_length=2_000_000)
    ciphertext: str | None = Field(None, max_length=2_000_000)
    wrapped_mek: str | None = Field(None, max_length=100_000)
    iv: str | None = Field(None, max_length=100)
    crypto_version: Literal[1] = 1
    crypto_metadata: dict | None = None
    # Coverage plumbing only (advisor UI deferred): optional free-form validated below.
    category: str | None = Field(None, max_length=50)
    coverage_tags: list[str] | None = Field(None, max_length=20)


MESSAGE_CATEGORIES = {
    "financial", "insurance", "digital_assets", "digital_identity",
    "digital_storage", "devices", "online_accounts", "property",
    "dependents", "business", "personal",
}


def _require_b64(value: str, field: str, max_raw: int) -> None:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be valid base64") from exc
    if len(raw) == 0 or len(raw) > max_raw:
        raise HTTPException(status_code=422, detail=f"{field} size invalid")


def _check_metadata(obj: object, field: str, max_keys: int = 20, max_serialized: int = 4000) -> None:
    """Bound free-form crypto metadata dicts (count, key length, depth, size)."""
    if obj is None:
        return
    if not isinstance(obj, dict) or len(obj) > max_keys:
        raise HTTPException(status_code=422, detail=f"{field} must be an object with <= {max_keys} keys")
    for k in obj:
        if not isinstance(k, str) or len(k) > 64:
            raise HTTPException(status_code=422, detail=f"{field} keys must be strings <= 64 chars")

    def _depth(v: object, d: int) -> int:
        if d > 3:
            raise HTTPException(status_code=422, detail=f"{field} nesting too deep")
        if isinstance(v, dict):
            return max([_depth(x, d + 1) for x in v.values()] or [d])
        if isinstance(v, list):
            if len(v) > 50:
                raise HTTPException(status_code=422, detail=f"{field} lists too long")
            for x in v:
                _depth(x, d + 1)
        return d

    _depth(obj, 0)
    try:
        serialized = json.dumps(obj)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be JSON-serializable") from exc
    if len(serialized) > max_serialized:
        raise HTTPException(status_code=422, detail=f"{field} too large")


class MessageMeta(BaseModel):
    id: int
    label: str
    created_at: str
    model_config = {"from_attributes": True}


class MessageDetail(BaseModel):
    id: int
    label: str
    encrypted_content: str
    ciphertext: str
    wrapped_mek: str
    iv: str
    crypto_version: int
    crypto_metadata: dict
    created_at: str
    category: str | None = None
    coverage_tags: list[str] = []
    model_config = {"from_attributes": True}


# Crypto Material Schemas
class VMKMeta(BaseModel):
    version: int
    algorithm: str
    salt: str
    iterations: int


class CryptoMaterialResponse(BaseModel):
    wrapped_vmk: str | None
    vmk_crypto_version: int | None
    vmk_kdf_algorithm: str | None
    vmk_kdf_salt: str | None
    vmk_kdf_parameters: dict | None


class CryptoMaterialRequest(BaseModel):
    wrapped_vmk: str = Field(..., min_length=1, max_length=100_000)
    vmk_crypto_version: Literal[1] = 1
    vmk_kdf_algorithm: Literal["PBKDF2-SHA256"] = "PBKDF2-SHA256"
    vmk_kdf_salt: str = Field(..., min_length=1, max_length=10_000)
    vmk_kdf_parameters: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_vault(db: Session, current_user: User | None = None) -> Vault:
    """Get vault scoped to user. Fail closed (no cross-tenant fallback)."""
    if current_user is not None:
        vault = db.query(Vault).filter(Vault.user_id == current_user.id).first()
        if vault:
            return vault
    raise HTTPException(status_code=404, detail="Vault not found")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/messages", status_code=status.HTTP_201_CREATED)
def save_message(
    data: MessageRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)

    ciphertext = data.ciphertext or data.encrypted_content
    if not ciphertext:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either ciphertext or encrypted_content must be provided.",
        )
    if not data.wrapped_mek:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="wrapped_mek is required.",
        )
    # Validate opaque blobs are base64 (fail fast, no silent corruption)
    _require_b64(ciphertext, "ciphertext", 2_000_000)
    _require_b64(data.wrapped_mek, "wrapped_mek", 100_000)
    if data.iv:
        _require_b64(data.iv, "iv", 64)

    metadata_dict = dict(data.crypto_metadata) if data.crypto_metadata else {}
    _check_metadata(data.crypto_metadata, "crypto_metadata")

    if data.iv and "iv" not in metadata_dict:
        metadata_dict["iv"] = data.iv

    if data.category is not None and data.category not in MESSAGE_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid category")
    tags = data.coverage_tags or []
    if len(tags) > 20 or any(not isinstance(t, str) or len(t) > 50 for t in tags):
        raise HTTPException(status_code=422, detail="Invalid coverage_tags")

    message = VaultMessage(
        vault_id=vault.id,
        label=data.label,
        ciphertext=ciphertext,
        wrapped_mek=data.wrapped_mek,
        crypto_version=data.crypto_version,
        crypto_metadata=json.dumps(metadata_dict),
        category=data.category,
        coverage_tags=json.dumps(tags),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    try:
        log_audit("message.create", "owner", current_user.id, vault.id)
    except Exception:
        pass
    return {"id": message.id, "message": "Message saved"}


@router.get("/messages", response_model=list[MessageMeta])
def list_messages(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    messages = (
        db.query(VaultMessage)
        .filter(VaultMessage.vault_id == vault.id)
        .order_by(VaultMessage.created_at.desc())
        .all()
    )
    return [
        MessageMeta(
            id=m.id,
            label=m.label,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in messages
    ]


@router.get("/messages/{message_id}", response_model=MessageDetail)
def load_message(
    message_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    message = (
        db.query(VaultMessage)
        .filter(VaultMessage.id == message_id, VaultMessage.vault_id == vault.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    try:
        metadata = json.loads(message.crypto_metadata) if message.crypto_metadata else {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Stored crypto metadata is corrupt") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="Stored crypto metadata is corrupt")
    iv_str = metadata.get("iv", "")
    try:
        tags = json.loads(message.coverage_tags) if message.coverage_tags else []
    except Exception:
        tags = []
    if not isinstance(tags, list):
        tags = []

    return MessageDetail(
        id=message.id,
        label=message.label,
        encrypted_content=message.ciphertext,
        ciphertext=message.ciphertext,
        wrapped_mek=message.wrapped_mek,
        iv=iv_str,
        crypto_version=message.crypto_version,
        crypto_metadata=metadata,
        created_at=message.created_at.isoformat() if message.created_at else "",
        category=message.category,
        coverage_tags=tags,
    )


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    message_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    message = (
        db.query(VaultMessage)
        .filter(VaultMessage.id == message_id, VaultMessage.vault_id == vault.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    db.delete(message)
    db.commit()
    try:
        log_audit("message.delete", "owner", current_user.id, vault.id)
    except Exception:
        pass


class MessageUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=200)
    encrypted_content: str | None = Field(None, max_length=2_000_000)
    ciphertext: str | None = Field(None, max_length=2_000_000)
    wrapped_mek: str | None = Field(None, max_length=100_000)
    iv: str | None = Field(None, max_length=100)
    crypto_metadata: dict | None = None
    category: str | None = Field(None, max_length=50)
    coverage_tags: list[str] | None = None


@router.put("/messages/{message_id}")
def update_message(
    message_id: int,
    data: MessageUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    message = (
        db.query(VaultMessage)
        .filter(VaultMessage.id == message_id, VaultMessage.vault_id == vault.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    ciphertext = data.ciphertext or data.encrypted_content
    if ciphertext:
        _require_b64(ciphertext, "ciphertext", 2_000_000)
        message.ciphertext = ciphertext

    if data.label is not None:
        message.label = data.label

    if data.category is not None:
        if data.category not in MESSAGE_CATEGORIES:
            raise HTTPException(status_code=422, detail="Invalid category")
        message.category = data.category

    if data.coverage_tags is not None:
        if len(data.coverage_tags) > 20 or any(
            not isinstance(t, str) or len(t) > 50 for t in data.coverage_tags
        ):
            raise HTTPException(status_code=422, detail="Invalid coverage_tags")
        message.coverage_tags = json.dumps(data.coverage_tags)

    if data.wrapped_mek is not None:
        _require_b64(data.wrapped_mek, "wrapped_mek", 100_000)
        message.wrapped_mek = data.wrapped_mek

    if data.iv is not None:
        _require_b64(data.iv, "iv", 64)

    if data.crypto_metadata is not None:
        _check_metadata(data.crypto_metadata, "crypto_metadata")
        merged = dict(data.crypto_metadata)
        if data.iv and "iv" not in merged:
            merged["iv"] = data.iv
        message.crypto_metadata = json.dumps(merged)
    elif data.iv:
        try:
            existing = json.loads(message.crypto_metadata) if message.crypto_metadata else {}
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing["iv"] = data.iv
        message.crypto_metadata = json.dumps(existing)

    message.updated_at = datetime.now(UTC)
    db.commit()
    try:
        log_audit("message.update", "owner", current_user.id, vault.id)
    except Exception:
        pass
    return {"id": message.id, "message": "Message updated"}


class WipeRequest(BaseModel):
    password: str = Field(..., min_length=12, max_length=256)
    confirm: Literal[True]


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
def wipe_vault(
    data: WipeRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Delete ALL messages for the user's vault (requires password + confirm)."""
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    vault = _get_vault(db, current_user)
    db.query(VaultMessage).filter(VaultMessage.vault_id == vault.id).delete()
    db.commit()
    try:
        log_audit("vault.wipe", "owner", current_user.id, vault.id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Crypto Material Endpoints
# ---------------------------------------------------------------------------

@router.get("/crypto-material", response_model=CryptoMaterialResponse)
def get_crypto_material(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Get wrapped VMK and KDF metadata for vault unlock."""
    vault = _get_vault(db, current_user)

    params = None
    if vault.vmk_kdf_parameters:
        try:
            params = json.loads(vault.vmk_kdf_parameters)
        except Exception:
            params = None

    return CryptoMaterialResponse(
        wrapped_vmk=vault.wrapped_vmk,
        vmk_crypto_version=vault.vmk_crypto_version,
        vmk_kdf_algorithm=vault.vmk_kdf_algorithm,
        vmk_kdf_salt=vault.vmk_kdf_salt,
        vmk_kdf_parameters=params,
    )


@router.put("/crypto-material")
def save_crypto_material(
    data: CryptoMaterialRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Save wrapped VMK and KDF metadata (initial setup or passphrase change)."""
    vault = _get_vault(db, current_user)

    _require_b64(data.wrapped_vmk, "wrapped_vmk", 100_000)
    _require_b64(data.vmk_kdf_salt, "vmk_kdf_salt", 10_000)
    _check_metadata(data.vmk_kdf_parameters, "vmk_kdf_parameters", max_keys=10, max_serialized=2000)
    iters = data.vmk_kdf_parameters.get("iterations")
    if not isinstance(iters, int) or iters < 100_000 or iters > 10_000_000:
        raise HTTPException(status_code=422, detail="iterations must be >= 100000")

    vault.wrapped_vmk = data.wrapped_vmk
    vault.vmk_crypto_version = data.vmk_crypto_version
    vault.vmk_kdf_algorithm = data.vmk_kdf_algorithm
    vault.vmk_kdf_salt = data.vmk_kdf_salt
    vault.vmk_kdf_parameters = json.dumps(data.vmk_kdf_parameters)
    vault.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(vault)
    try:
        log_audit("vault.crypto_material_save", "owner", current_user.id, vault.id)
    except Exception:
        pass

    return {"message": "Crypto material saved successfully"}


class ShareAssignmentOut(BaseModel):
    beneficiary_id: int
    beneficiary_name: str
    beneficiary_email: str
    share_index: int | None
    invitation_status: str


@router.get("/share-assignments", response_model=list[ShareAssignmentOut])
def list_share_assignments_vault(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Metadata-only share assignments (alias of /access/share-assignments per API spec)."""
    from models import Beneficiary as BeneficiaryModel

    vault = _get_vault(db, current_user)
    rows = db.query(BeneficiaryModel).filter(BeneficiaryModel.vault_id == vault.id).all()
    return [
        ShareAssignmentOut(
            beneficiary_id=r.id,
            beneficiary_name=r.name,
            beneficiary_email=r.email,
            share_index=r.share_index,
            invitation_status=r.invitation_status,
        )
        for r in rows
    ]
