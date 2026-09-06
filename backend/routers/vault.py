import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from deps import get_db, require_owner
from models import User, Vault, VaultMessage

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
    crypto_version: int | None = 1
    crypto_metadata: dict | str | None = None


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
    wrapped_vmk: str
    vmk_crypto_version: int
    vmk_kdf_algorithm: str
    vmk_kdf_salt: str
    vmk_kdf_parameters: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_vault(db: Session, current_user: User | None = None) -> Vault:
    """Get vault scoped to user, with single-tenant fallback for legacy/test rows."""
    if current_user:
        vault = db.query(Vault).filter(Vault.user_id == current_user.id).first()
        if vault:
            return vault
    vault = db.query(Vault).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    return vault


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

    metadata_dict = {}
    if isinstance(data.crypto_metadata, dict):
        metadata_dict = data.crypto_metadata
    elif isinstance(data.crypto_metadata, str):
        try:
            metadata_dict = json.loads(data.crypto_metadata)
        except Exception:
            metadata_dict = {}

    if data.iv and "iv" not in metadata_dict:
        metadata_dict["iv"] = data.iv

    message = VaultMessage(
        vault_id=vault.id,
        label=data.label,
        ciphertext=ciphertext,
        wrapped_mek=data.wrapped_mek or "",
        crypto_version=data.crypto_version or 1,
        crypto_metadata=json.dumps(metadata_dict),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
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

    metadata = {}
    if message.crypto_metadata:
        try:
            metadata = json.loads(message.crypto_metadata)
        except Exception:
            metadata = {}
    iv_str = metadata.get("iv", "")

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


@router.put("/messages/{message_id}")
def update_message(
    message_id: int,
    data: MessageRequest,
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
        message.ciphertext = ciphertext

    message.label = data.label

    if data.wrapped_mek is not None:
        message.wrapped_mek = data.wrapped_mek

    if data.crypto_version is not None:
        message.crypto_version = data.crypto_version

    if data.crypto_metadata is not None:
        if isinstance(data.crypto_metadata, dict):
            message.crypto_metadata = json.dumps(data.crypto_metadata)
        else:
            message.crypto_metadata = str(data.crypto_metadata)

    message.updated_at = datetime.now(UTC)
    db.commit()
    return {"id": message.id, "message": "Message updated"}


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
def wipe_vault(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Delete ALL messages for the user's vault."""
    vault = _get_vault(db, current_user)
    db.query(VaultMessage).filter(VaultMessage.vault_id == vault.id).delete()
    db.commit()


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

    # Validate crypto version
    if data.vmk_crypto_version != 1:
        raise HTTPException(status_code=400, detail="Unsupported crypto version")

    if data.vmk_kdf_algorithm != "PBKDF2-SHA256":
        raise HTTPException(status_code=400, detail="Unsupported KDF algorithm")

    vault.wrapped_vmk = data.wrapped_vmk
    vault.vmk_crypto_version = data.vmk_crypto_version
    vault.vmk_kdf_algorithm = data.vmk_kdf_algorithm
    vault.vmk_kdf_salt = data.vmk_kdf_salt
    vault.vmk_kdf_parameters = json.dumps(data.vmk_kdf_parameters)
    vault.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(vault)

    return {"message": "Crypto material saved successfully"}