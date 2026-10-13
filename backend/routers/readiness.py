"""Separate authentication, distribution and owner-reported recovery evidence."""

import hashlib
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_db, require_owner
from models import Beneficiary, RecoveryCeremony
from routers.vault import _get_vault
from services.audit import record_audit
from services.trigger_service import lock_status

router = APIRouter(prefix="/vault", dependencies=[Depends(require_owner)], tags=["readiness"])


def assignment_signature(db, vault):
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
        and b.share_index
        and b.ceremony_generation == vault.recovery_generation
    }
    return signature, len(eligible)


@router.get("/readiness")
def readiness(user=Depends(require_owner), db=Depends(get_db)):
    vault = _get_vault(db, user)
    signature, eligible = assignment_signature(db, vault)
    ceremony = (
        db.query(RecoveryCeremony)
        .filter_by(vault_id=vault.id, generation=vault.recovery_generation, status="FINALIZED")
        .first()
    )
    drill = json.loads(ceremony.drill_data) if ceremony and ceremony.drill_data else None
    valid = bool(
        drill
        and drill["material_revision"] == vault.material_revision
        and drill["assignment_signature"] == signature
    )
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
        "owner_reported_drill": drill if valid else None,
        "independently_verified_possession": False,
    }


class DrillReport(BaseModel):
    material_revision: int = Field(..., ge=1)
    assignment_signature: str = Field(..., pattern="^[0-9a-f]{64}$")
    generation: str = Field(..., pattern="^[0-9a-f]{32}$")


@router.post("/drill")
def report_drill(data: DrillReport, user=Depends(require_owner), db=Depends(get_db)):
    vault = _get_vault(db, user)
    lock_status(db, vault.id)
    db.refresh(vault)
    signature, _ = assignment_signature(db, vault)
    if (
        vault.material_revision != data.material_revision
        or vault.recovery_generation != data.generation
        or signature != data.assignment_signature
    ):
        raise HTTPException(409, "Recovery setup changed; repeat the drill")
    row = (
        db.query(RecoveryCeremony)
        .filter_by(vault_id=vault.id, generation=data.generation, status="FINALIZED")
        .first()
    )
    if not row:
        raise HTTPException(409, "A finalized current ceremony is required")
    evidence = {
        **data.model_dump(),
        "reported_at": datetime.now(UTC).isoformat(),
        "verifier": "owner_report",
    }
    row.drill_data = json.dumps(evidence)
    record_audit(db, vault.id, "owner", user.id, "recovery.drill_reported", {"ceremony_id": row.id})
    db.commit()
    return {"message": "Owner-reported drill recorded; possession is not independently verified"}
