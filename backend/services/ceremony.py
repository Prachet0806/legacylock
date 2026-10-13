"""Draft/finalize ceremonies preserve active material until an atomic commit."""

import json
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models import Beneficiary, RecoveryCeremony, Vault
from services.audit import record_audit


def create_draft(db, user, data):
    from routers.vault import validate_material, writable

    vault = db.query(Vault).filter_by(user_id=user.id, is_primary=True).first()
    if vault is None:
        vault = Vault(
            user_id=user.id,
            name="Primary Vault",
            material_revision=0,
            recovery_status="UNINITIALIZED",
        )
        db.add(vault)
        db.flush()
    writable(db, vault, data.expected_revision)
    if not re.fullmatch(r"[0-9a-f]{32}", data.recovery_generation):
        raise HTTPException(422, "Generation must be canonical lowercase hexadecimal")
    if not 1 <= data.recovery_threshold <= data.recovery_total <= 10:
        raise HTTPException(422, "Require 1 <= k <= n <= 10")
    if vault.recovery_generation == data.recovery_generation:
        raise HTTPException(409, "Generation was already used")
    if vault.wrapped_vmk:
        if data.initial_material is not None:
            raise HTTPException(409, "Existing vault keys cannot be replaced by setup")
    else:
        if data.initial_material is None or data.initial_material.expected_revision != 0:
            raise HTTPException(422, "Initial draft requires a complete wrapping bundle")
        validate_material(data.initial_material)
    db.query(RecoveryCeremony).filter_by(vault_id=vault.id, status="DRAFT").update(
        {"status": "CANCELLED", "initial_material": None}, synchronize_session=False
    )
    row = RecoveryCeremony(
        vault_id=vault.id,
        generation=data.recovery_generation,
        threshold=data.recovery_threshold,
        total=data.recovery_total,
        status="DRAFT",
        expected_revision=data.expected_revision,
        initial_material=json.dumps(data.initial_material.model_dump())
        if data.initial_material
        else None,
    )
    db.add(row)
    if not vault.wrapped_vmk:
        vault.recovery_status = "DRAFT"
    record_audit(db, vault.id, "owner", user.id, "ceremony.draft", {})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Generation was already used") from exc
    return {
        "ceremony_id": row.id,
        "recovery_threshold": row.threshold,
        "recovery_total": row.total,
        "recovery_generation": row.generation,
        "recovery_status": "DRAFT",
        "material_revision": vault.material_revision,
    }


def finalize(db, user, ident, indexes):
    from routers.vault import CryptoMaterialRequest, apply_material, writable

    row = (
        db.query(RecoveryCeremony)
        .join(Vault)
        .filter(RecoveryCeremony.id == ident, Vault.user_id == user.id)
        .first()
    )
    if row is None:
        raise HTTPException(404, "Ceremony not found")
    vault = db.get(Vault, row.vault_id)
    writable(db, vault)
    db.refresh(row)
    if row.status == "FINALIZED":
        return {"message": "Already finalized", "material_revision": vault.material_revision}
    if row.status != "DRAFT" or vault.material_revision != row.expected_revision:
        raise HTTPException(409, "Draft is stale or cancelled; restart with fresh shares")
    if sorted(indexes) != list(range(1, row.total + 1)):
        raise HTTPException(422, "Acknowledge every distinct share; this is an owner assertion")
    if (
        db.query(Beneficiary)
        .filter(Beneficiary.vault_id == vault.id, Beneficiary.share_index > row.total)
        .first()
    ):
        raise HTTPException(409, "Reassign out-of-range beneficiaries first")
    db.query(RecoveryCeremony).filter_by(vault_id=vault.id, status="FINALIZED").update(
        {"status": "SUPERSEDED"}, synchronize_session=False
    )
    if row.initial_material:
        apply_material(vault, CryptoMaterialRequest(**json.loads(row.initial_material)))
    else:
        vault.material_revision += 1
    vault.recovery_threshold, vault.recovery_total = row.threshold, row.total
    vault.recovery_generation, vault.recovery_status = row.generation, "READY"
    vault.updated_at = datetime.now(UTC)
    row.status, row.initial_material, row.acknowledgments = "FINALIZED", None, json.dumps(indexes)
    # A new share distribution requires explicit reassignment; do not assert possession.
    db.query(Beneficiary).filter_by(vault_id=vault.id).update(
        {"ceremony_generation": None}, synchronize_session=False
    )
    record_audit(db, vault.id, "owner", user.id, "ceremony.finalize", {"ceremony_id": row.id})
    db.commit()
    return {"message": "Ceremony finalized", "material_revision": vault.material_revision}


def cancel(db, user, ident):
    from routers.vault import writable

    row = (
        db.query(RecoveryCeremony)
        .join(Vault)
        .filter(RecoveryCeremony.id == ident, Vault.user_id == user.id)
        .first()
    )
    if row is None:
        raise HTTPException(404, "Ceremony not found")
    vault = db.get(Vault, row.vault_id)
    writable(db, vault)
    db.refresh(row)
    if row.status == "FINALIZED":
        raise HTTPException(409, "Cannot cancel a finalized ceremony")
    row.status, row.initial_material = "CANCELLED", None
    if not vault.wrapped_vmk:
        vault.recovery_status = "UNINITIALIZED"
    record_audit(db, vault.id, "owner", user.id, "ceremony.cancel", {})
    db.commit()
    return {"message": "Draft cancelled"}
