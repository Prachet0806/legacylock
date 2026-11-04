"""Shared recovery evidence used by status reporting and release gates."""

import hashlib
import json
from typing import cast

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Beneficiary, RecoveryCeremony, Vault


def assignment_signature(db: Session, vault: Vault) -> tuple[str, int]:
    rows = db.query(Beneficiary).filter_by(vault_id=vault.id).order_by(Beneficiary.id).all()
    binding = [
        (b.id, b.contact_revision, b.share_index, b.ceremony_generation, b.invitation_status)
        for b in rows
    ]
    signature = hashlib.sha256(json.dumps(binding).encode()).hexdigest()
    eligible = {
        b.share_index
        for b in rows
        if b.invitation_status == "accepted"
        and b.share_index is not None
        and b.ceremony_generation == vault.recovery_generation
    }
    return signature, len(eligible)


def current_ceremony(db: Session, vault: Vault) -> RecoveryCeremony | None:
    if not vault.recovery_generation:
        return None
    return (
        db.query(RecoveryCeremony)
        .filter_by(vault_id=vault.id, generation=vault.recovery_generation, status="FINALIZED")
        .first()
    )


def current_drill(db: Session, vault: Vault, signature: str) -> dict | None:
    ceremony = current_ceremony(db, vault)
    if not ceremony or not ceremony.drill_data:
        return None
    try:
        drill = json.loads(cast(str, ceremony.drill_data))
    except (TypeError, ValueError):
        return None
    if not isinstance(drill, dict):
        return None
    if (
        ceremony.expected_revision + 1 != vault.material_revision
        or ceremony.threshold != vault.recovery_threshold
        or ceremony.total != vault.recovery_total
        or drill.get("material_revision") != vault.material_revision
        or drill.get("assignment_signature") != signature
        or drill.get("generation") != vault.recovery_generation
        or drill.get("verifier") != "owner_report"
    ):
        return None
    return drill


def recovery_evidence(db: Session, vault: Vault) -> dict:
    signature, eligible = assignment_signature(db, vault)
    drill = current_drill(db, vault, signature)
    return {
        "initialized": bool(vault.wrapped_vmk),
        "material_revision": vault.material_revision,
        "ceremony_status": vault.recovery_status,
        "generation": vault.recovery_generation,
        "threshold": vault.recovery_threshold,
        "total": vault.recovery_total,
        "eligible_assignments": eligible,
        "quorum_assigned": eligible >= vault.recovery_threshold,
        "assignment_signature": signature,
        "armed": bool(vault.status and vault.status.armed),
        "owner_reported_drill": drill,
        "independently_verified_possession": False,
    }


def release_ready(db: Session, vault: Vault) -> bool:
    evidence = recovery_evidence(db, vault)
    threshold, total = vault.recovery_threshold, vault.recovery_total
    return bool(
        evidence["initialized"]
        and evidence["ceremony_status"] == "READY"
        and evidence["generation"]
        and threshold is not None
        and total is not None
        and threshold >= 1
        and total >= threshold
        and current_ceremony(db, vault) is not None
        and evidence["quorum_assigned"]
        and evidence["owner_reported_drill"] is not None
    )


def require_release_ready(db: Session, vault_id: int) -> None:
    vault = db.query(Vault).filter_by(id=vault_id).with_for_update().one_or_none()
    if vault is None or not release_ready(db, vault):
        raise HTTPException(
            status_code=409,
            detail="Recovery setup is not ready for release",
        )
