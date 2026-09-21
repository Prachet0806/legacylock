import base64
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from deps import get_db, require_owner
from logging_config import log_audit
from models import MessageCategory, User, Vault, VaultMessage
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


class CryptoMaterialRequest(BaseModel):
    wrapped_vmk: str = Field(..., min_length=1, max_length=100_000)
    vmk_crypto_version: Literal[1] = 1
    vmk_kdf_algorithm: Literal["PBKDF2-SHA256"] = "PBKDF2-SHA256"
    vmk_kdf_salt: str = Field(..., min_length=1, max_length=10_000)
    vmk_kdf_parameters: dict
    # Optional per-vault Shamir policy (k-of-n). When omitted, existing policy
    # is preserved (legacy default 2-of-3). When k/n change, a fresh
    # recovery_generation (new ceremony) is required — policy metadata must
    # never silently diverge from the distributed share set.
    recovery_threshold: int | None = Field(None, ge=1, le=10)
    recovery_total: int | None = Field(None, ge=1, le=10)
    recovery_generation: str | None = Field(None, min_length=32, max_length=32)


class RecoveryPolicyRequest(BaseModel):
    recovery_threshold: int = Field(..., ge=1, le=10)
    recovery_total: int = Field(..., ge=1, le=10)


class RecoveryCeremonyRequest(BaseModel):
    recovery_threshold: int = Field(..., ge=1, le=10)
    recovery_total: int = Field(..., ge=1, le=10)
    recovery_generation: str = Field(..., min_length=32, max_length=32)


class RecoveryPolicyResponse(BaseModel):
    recovery_threshold: int
    recovery_total: int
    recovery_generation: str | None = None
    recovery_status: str = "READY"


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

    # Validate opaque blobs are base64 (fail fast, no silent corruption)
    _require_b64(data.ciphertext, "ciphertext", 2_000_000)
    _require_b64(data.wrapped_mek, "wrapped_mek", 100_000)

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
    db.commit()
    try:
        log_audit("message.delete", "owner", current_user.id, vault.id)
    except Exception:
        pass


class MessageUpdate(BaseModel):
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

    if data.crypto_metadata is not None:
        _check_metadata(data.crypto_metadata, "crypto_metadata")
        message.crypto_metadata = json.dumps(dict(data.crypto_metadata))

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
    """Save wrapped VMK and KDF metadata (initial setup or passphrase change).

    This is the explicit vault-provisioning step: it creates the owner's
    primary vault if none exists (login deliberately does not).
    """
    vault = (
        db.query(Vault).filter(Vault.user_id == current_user.id, Vault.is_primary == True).first()
    )
    if not vault:
        vault = Vault(user_id=current_user.id, name="Primary Vault", is_primary=True)
        db.add(vault)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            vault = (
                db.query(Vault)
                .filter(Vault.user_id == current_user.id, Vault.is_primary == True)
                .first()
            )
            if not vault:
                raise
        db.refresh(vault)

    _require_b64(data.wrapped_vmk, "wrapped_vmk", 100_000)
    _require_b64(data.vmk_kdf_salt, "vmk_kdf_salt", 10_000)
    _check_metadata(data.vmk_kdf_parameters, "vmk_kdf_parameters", max_keys=10, max_serialized=2000)
    contract = KDF_CONTRACTS.get(data.vmk_crypto_version)
    if contract is None:
        raise HTTPException(status_code=422, detail="Unsupported crypto version")
    if data.vmk_kdf_algorithm != contract["algorithm"]:
        raise HTTPException(status_code=422, detail="KDF algorithm mismatch for crypto version")
    if data.vmk_kdf_parameters.get("iterations") != contract["iterations"]:
        raise HTTPException(status_code=422, detail="KDF iterations mismatch for crypto version")
    try:
        salt_len = len(base64.b64decode(data.vmk_kdf_salt, validate=True))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="vmk_kdf_salt must be valid base64") from exc
    if salt_len != contract["salt_bytes"]:
        raise HTTPException(status_code=422, detail="KDF salt length mismatch for crypto version")

    if data.recovery_threshold is not None or data.recovery_total is not None:
        k = data.recovery_threshold if data.recovery_threshold is not None else _policy_of(vault)[0]
        n = data.recovery_total if data.recovery_total is not None else _policy_of(vault)[1]
        _validate_policy(k, n)
        _ensure_policy_fits_assignments(db, vault, n)
        cur_k, cur_n = _policy_of(vault)
        if (k, n) != (cur_k, cur_n) or (
            vault.recovery_generation and data.recovery_generation != vault.recovery_generation
        ):
            # New or changed policy must arrive with a fresh ceremony generation.
            if not data.recovery_generation or not _valid_generation(data.recovery_generation):
                raise HTTPException(
                    status_code=409,
                    detail="Policy change requires a fresh recovery_generation (new ceremony)",
                )
            if data.recovery_generation == (vault.recovery_generation or ""):
                raise HTTPException(
                    status_code=409,
                    detail="recovery_generation reuse: generate a new ceremony",
                )
            vault.recovery_generation = data.recovery_generation.lower()
            vault.recovery_status = "READY"
        elif data.recovery_generation and not vault.recovery_generation:
            if not _valid_generation(data.recovery_generation):
                raise HTTPException(status_code=422, detail="Invalid recovery_generation")
            vault.recovery_generation = data.recovery_generation.lower()
            vault.recovery_status = "READY"
        vault.recovery_threshold = k
        vault.recovery_total = n

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
        recovery_status=vault.recovery_status or "READY",
    )


@router.post("/recovery-ceremony", response_model=RecoveryPolicyResponse)
def post_recovery_ceremony(
    data: RecoveryCeremonyRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Commit a client-side recovery ceremony: new generation binds policy to shares.

    The server never sees raw shares — only (generation, k, n). Generation must
    be fresh (never reused) so old share sets cannot be confused with the new one.
    """
    from models import Vault as VaultModel

    vault = (
        db.query(VaultModel)
        .filter(VaultModel.user_id == current_user.id, VaultModel.is_primary == True)
        .first()
    )
    if not vault:
        vault = VaultModel(user_id=current_user.id, name="Primary Vault", is_primary=True)
        db.add(vault)
        db.commit()
        db.refresh(vault)
    _validate_policy(data.recovery_threshold, data.recovery_total)
    _ensure_policy_fits_assignments(db, vault, data.recovery_total)
    gen = data.recovery_generation.lower()
    if not _valid_generation(gen):
        raise HTTPException(status_code=422, detail="Invalid recovery_generation")
    if gen == (vault.recovery_generation or ""):
        raise HTTPException(status_code=409, detail="recovery_generation reuse: generate a new one")
    vault.recovery_threshold = data.recovery_threshold
    vault.recovery_total = data.recovery_total
    vault.recovery_generation = gen
    vault.recovery_status = "READY"
    vault.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(vault)
    try:
        log_audit("vault.recovery_ceremony", "owner", current_user.id, vault.id)
    except Exception:
        pass
    return RecoveryPolicyResponse(
        recovery_threshold=vault.recovery_threshold,
        recovery_total=vault.recovery_total,
        recovery_generation=vault.recovery_generation,
        recovery_status=vault.recovery_status,
    )


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
        vault = Vault(user_id=current_user.id, name="Primary Vault", is_primary=True)
        db.add(vault)
        db.commit()
        db.refresh(vault)
    _validate_policy(data.recovery_threshold, data.recovery_total)
    cur_k, cur_n = _policy_of(vault)
    if (data.recovery_threshold, data.recovery_total) != (cur_k, cur_n):
        raise HTTPException(
            status_code=409,
            detail="Policy change requires POST /vault/recovery-ceremony with a fresh generation",
        )
    _ensure_policy_fits_assignments(db, vault, data.recovery_total)
    vault.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(vault)
    return RecoveryPolicyResponse(
        recovery_threshold=vault.recovery_threshold,
        recovery_total=vault.recovery_total,
        recovery_generation=vault.recovery_generation,
        recovery_status=vault.recovery_status or "READY",
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
