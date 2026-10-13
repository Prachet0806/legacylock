import base64
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from deps import get_db, require_owner
from models import MessageCategory, User, Vault, VaultMessage
from services.audit import record_audit
from services.auth import verify_password
from services.trigger_service import lock_status

router = APIRouter(
    prefix="/vault",
    tags=["vault"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MessageRequest(BaseModel):
    material_revision: int = Field(..., ge=1)
    label: str = Field(..., min_length=1, max_length=200)
    ciphertext: str = Field(..., max_length=2_000_000)
    wrapped_mek: str = Field(..., max_length=100_000)
    crypto_version: Literal[1] = 1
    # IV travels inside crypto_metadata (canonical shape); no top-level iv.
    crypto_metadata: dict | None = None
    # Coverage plumbing only (advisor UI deferred): optional free-form validated below.
    category: str | None = Field(None, max_length=50)
    coverage_tags: list[str] | None = Field(None, max_length=20)


MESSAGE_CATEGORIES = {c.value for c in MessageCategory}


def _require_b64(value: str, field: str, max_raw: int) -> None:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be valid base64") from exc
    if len(raw) == 0 or len(raw) > max_raw:
        raise HTTPException(status_code=422, detail=f"{field} size invalid")


def _check_metadata(
    obj: object, field: str, max_keys: int = 20, max_serialized: int = 4000
) -> None:
    """Bound free-form crypto metadata dicts (count, key length, depth, size)."""
    if obj is None:
        return
    if not isinstance(obj, dict) or len(obj) > max_keys:
        raise HTTPException(
            status_code=422, detail=f"{field} must be an object with <= {max_keys} keys"
        )
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
    category: str | None = None
    model_config = {"from_attributes": True}


class MessageDetail(BaseModel):
    id: int
    label: str
    ciphertext: str
    wrapped_mek: str
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
    material_revision: int = 0


class CryptoMaterialRequest(BaseModel):
    model_config = {"extra": "forbid"}
    wrapped_vmk: str = Field(..., min_length=1, max_length=100_000)
    vmk_crypto_version: Literal[1] = 1
    vmk_kdf_algorithm: Literal["PBKDF2-SHA256"] = "PBKDF2-SHA256"
    vmk_kdf_salt: str = Field(..., min_length=1, max_length=10_000)
    vmk_kdf_parameters: dict
    expected_revision: int = Field(..., ge=0)


class RecoveryPolicyRequest(BaseModel):
    recovery_threshold: int = Field(..., ge=1, le=10)
    recovery_total: int = Field(..., ge=1, le=10)


class RecoveryCeremonyRequest(BaseModel):
    recovery_threshold: int = Field(..., ge=1, le=10)
    recovery_total: int = Field(..., ge=1, le=10)
    recovery_generation: str = Field(..., min_length=32, max_length=32)
    expected_revision: int = Field(..., ge=0)
    initial_material: CryptoMaterialRequest | None = None


class RecoveryPolicyResponse(BaseModel):
    recovery_threshold: int
    recovery_total: int
    recovery_generation: str | None = None
    recovery_status: str = "READY"
    ceremony_id: int | None = None
    material_revision: int = 0


def validate_material(data):
    _require_b64(data.wrapped_vmk, "wrapped_vmk", 40)
    if len(base64.b64decode(data.wrapped_vmk, validate=True)) != 40:
        raise HTTPException(422, "wrapped_vmk must encode a 40-byte AES-KW value")
    _require_b64(data.vmk_kdf_salt, "vmk_kdf_salt", 16)
    if len(base64.b64decode(data.vmk_kdf_salt, validate=True)) != 16:
        raise HTTPException(422, "Salt must encode 16 bytes")
    if data.vmk_kdf_parameters != {"iterations": 600_000}:
        raise HTTPException(422, "Version 1 creation requires 600000 iterations")


def apply_material(vault, data):
    vault.wrapped_vmk = data.wrapped_vmk
    vault.vmk_crypto_version = data.vmk_crypto_version
    vault.vmk_kdf_algorithm = data.vmk_kdf_algorithm
    vault.vmk_kdf_salt = data.vmk_kdf_salt
    vault.vmk_kdf_parameters = json.dumps(data.vmk_kdf_parameters)
    vault.material_revision += 1


def writable(db, vault, expected=None):
    vs = lock_status(db, vault.id)
    db.refresh(vault)
    if vs.state == "triggered":
        raise HTTPException(
            409, "Released vaults are read-only; export or deletion remain available"
        )
    if expected is not None and vault.material_revision != expected:
        raise HTTPException(409, "Vault key material changed; unlock again")


def validate_message(ciphertext, wrapped_mek, metadata):
    _require_b64(ciphertext, "ciphertext", 1024 * 1024 + 16)
    if len(base64.b64decode(ciphertext, validate=True)) < 16:
        raise HTTPException(422, "Ciphertext must include a GCM authentication tag")
    _require_b64(wrapped_mek, "wrapped_mek", 40)
    if len(base64.b64decode(wrapped_mek, validate=True)) != 40:
        raise HTTPException(422, "wrapped_mek must encode 40 bytes")
    _check_metadata(metadata, "crypto_metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("iv"), str):
        raise HTTPException(422, "Version 1 metadata requires an IV")
    _require_b64(metadata["iv"], "iv", 12)
    if len(base64.b64decode(metadata["iv"], validate=True)) != 12:
        raise HTTPException(422, "IV must encode 12 bytes")


# Exact KDF contract per crypto version — clients may not negotiate weaker
# work factors. Add a v2 entry here (and only here) to rotate parameters.
KDF_CONTRACTS: dict[int, dict[str, object]] = {
    1: {"algorithm": "PBKDF2-SHA256", "iterations": 600_000, "salt_bytes": 16},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_vault(db: Session, current_user: User | None = None) -> Vault:
    """Get vault scoped to user. Fail closed (no cross-tenant fallback)."""
    if current_user is not None:
        vault = (
            db.query(Vault)
            .filter(Vault.user_id == current_user.id, Vault.is_primary == True)
            .first()
        )
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
    writable(db, vault, data.material_revision)
    if not vault.wrapped_vmk:
        raise HTTPException(409, "Finalize vault setup before saving messages")
    validate_message(data.ciphertext, data.wrapped_mek, data.crypto_metadata)

    metadata_dict = dict(data.crypto_metadata) if data.crypto_metadata else {}
    _check_metadata(data.crypto_metadata, "crypto_metadata")

    if data.category is not None and data.category not in MESSAGE_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid category")
    tags = data.coverage_tags or []
    if len(tags) > 20 or any(not isinstance(t, str) or len(t) > 50 for t in tags):
        raise HTTPException(status_code=422, detail="Invalid coverage_tags")

    message = VaultMessage(
        vault_id=vault.id,
        label=data.label,
        ciphertext=data.ciphertext,
        wrapped_mek=data.wrapped_mek,
        crypto_version=data.crypto_version,
        crypto_metadata=json.dumps(metadata_dict),
        category=data.category,
        coverage_tags=json.dumps(tags),
    )
    db.add(message)
    record_audit(db, vault.id, "owner", current_user.id, "message.create", {})
    db.commit()
    db.refresh(message)
    return {"id": message.id, "message": "Message saved"}


@router.get("/messages", response_model=list[MessageMeta])
def list_messages(
    before_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    vault = _get_vault(db, current_user)
    messages = (
        db.query(
            VaultMessage.id, VaultMessage.label, VaultMessage.created_at, VaultMessage.category
        )
        .filter(VaultMessage.vault_id == vault.id)
        .filter(VaultMessage.id < before_id if before_id else True)
        .order_by(VaultMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [
        MessageMeta(
            id=m.id,
            label=m.label,
            created_at=m.created_at.isoformat() if m.created_at else "",
            category=m.category,
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
    try:
        tags = json.loads(message.coverage_tags) if message.coverage_tags else []
    except Exception:
        tags = []
    if not isinstance(tags, list):
        tags = []

    return MessageDetail(
        id=message.id,
        label=message.label,
        ciphertext=message.ciphertext,
        wrapped_mek=message.wrapped_mek,
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
    record_audit(db, vault.id, "owner", current_user.id, "message.delete", {})
    db.commit()


class MessageUpdate(BaseModel):
    material_revision: int | None = Field(None, ge=1)
    label: str | None = Field(None, min_length=1, max_length=200)
    ciphertext: str | None = Field(None, max_length=2_000_000)
    wrapped_mek: str | None = Field(None, max_length=100_000)
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
    writable(db, vault, data.material_revision)
    crypto_fields = {"ciphertext", "wrapped_mek", "crypto_metadata"}
    if crypto_fields & data.model_fields_set:
        if not crypto_fields <= data.model_fields_set or data.material_revision is None:
            raise HTTPException(
                422, "Crypto replacement requires complete envelope and material revision"
            )
        validate_message(data.ciphertext, data.wrapped_mek, data.crypto_metadata)
    message = (
        db.query(VaultMessage)
        .filter(VaultMessage.id == message_id, VaultMessage.vault_id == vault.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if data.ciphertext is not None:
        _require_b64(data.ciphertext, "ciphertext", 2_000_000)
        message.ciphertext = data.ciphertext

    if data.label is not None:
        message.label = data.label

    if "category" in data.model_fields_set:
        if data.category is not None and data.category not in MESSAGE_CATEGORIES:
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

    if data.crypto_metadata is not None:
        _check_metadata(data.crypto_metadata, "crypto_metadata")
        message.crypto_metadata = json.dumps(dict(data.crypto_metadata))

    message.updated_at = datetime.now(UTC)
    record_audit(db, vault.id, "owner", current_user.id, "message.update", {})
    db.commit()
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
    record_audit(db, vault.id, "owner", current_user.id, "vault.wipe", {})
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
        material_revision=vault.material_revision,
    )


def _validate_policy(k: int, n: int) -> None:
    if k < 1 or k > n or n < 1 or n > 10:
        raise HTTPException(
            status_code=422, detail="require 1 <= recovery_threshold <= recovery_total <= 10"
        )


def _policy_of(vault: Vault) -> tuple[int, int]:
    return int(vault.recovery_threshold or 2), int(vault.recovery_total or 3)


def _ensure_policy_fits_assignments(db: Session, vault: Vault, n: int) -> None:
    from models import Beneficiary as BeneficiaryModel

    bad = (
        db.query(BeneficiaryModel)
        .filter(BeneficiaryModel.vault_id == vault.id, BeneficiaryModel.share_index > n)
        .first()
    )
    if bad:
        raise HTTPException(
            status_code=409,
            detail="recovery_total smaller than an assigned share_index; reassign first",
        )


@router.put("/crypto-material")
def save_crypto_material(
    data: CryptoMaterialRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    validate_material(data)
    vault = _get_vault(db, current_user)
    writable(db, vault, data.expected_revision)
    if not vault.wrapped_vmk:
        raise HTTPException(409, "Initial setup requires a draft and finalization")
    apply_material(vault, data)
    record_audit(db, vault.id, "owner", current_user.id, "vault.rewrap", {})
    db.commit()
    return {"message": "Wrapping bundle updated", "material_revision": vault.material_revision}


def _valid_generation(g: str | None) -> bool:
    if not g or len(g) != 32:
        return False
    try:
        int(g, 16)
        return True
    except ValueError:
        return False


@router.get("/recovery-policy", response_model=RecoveryPolicyResponse)
def get_recovery_policy(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Return the vault's Shamir k-of-n policy + ceremony binding."""
    vault = _get_vault(db, current_user)
    k, n = _policy_of(vault)
    return RecoveryPolicyResponse(
        recovery_threshold=k,
        recovery_total=n,
        recovery_generation=vault.recovery_generation,
        recovery_status=vault.recovery_status or "LEGACY",
        material_revision=vault.material_revision,
    )


@router.post("/recovery-ceremony", response_model=RecoveryPolicyResponse)
def post_recovery_ceremony(
    data: RecoveryCeremonyRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from services.ceremony import create_draft

    return create_draft(db, current_user, data)


class CeremonyFinalize(BaseModel):
    stored_indexes: list[int] = Field(..., max_length=10)


@router.post("/recovery-ceremony/{ceremony_id}/finalize")
def finalize_ceremony(
    ceremony_id: int,
    data: CeremonyFinalize,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from services.ceremony import finalize

    return finalize(db, current_user, ceremony_id, data.stored_indexes)


@router.delete("/recovery-ceremony/{ceremony_id}")
def cancel_ceremony(
    ceremony_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)
):
    from services.ceremony import cancel

    return cancel(db, current_user, ceremony_id)


@router.put("/recovery-policy", response_model=RecoveryPolicyResponse)
def put_recovery_policy(
    data: RecoveryPolicyRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Legacy policy setter — now ceremony-guarded.

    Changing k/n without a fresh ceremony generation would let policy metadata
    diverge from the distributed share set (the old shares stay mathematically
    usable). Direct silent changes are rejected with 409; use
    POST /vault/recovery-ceremony with a fresh recovery_generation instead.
    Re-saving the identical policy is allowed (no-op).
    """
    vault = (
        db.query(Vault).filter(Vault.user_id == current_user.id, Vault.is_primary == True).first()
    )
    if not vault:
        raise HTTPException(404, "Vault not found; start a recovery ceremony")
    _validate_policy(data.recovery_threshold, data.recovery_total)
    cur_k, cur_n = _policy_of(vault)
    if (data.recovery_threshold, data.recovery_total) != (cur_k, cur_n):
        raise HTTPException(
            status_code=409,
            detail="Policy change requires POST /vault/recovery-ceremony with a fresh generation",
        )
    _ensure_policy_fits_assignments(db, vault, data.recovery_total)
    # The compatibility endpoint is a read-only no-op, including after release.
    return RecoveryPolicyResponse(
        recovery_threshold=vault.recovery_threshold,
        recovery_total=vault.recovery_total,
        recovery_generation=vault.recovery_generation,
        recovery_status=vault.recovery_status or "LEGACY",
        material_revision=vault.material_revision,
    )


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
