"""Separate authentication, distribution and owner-reported recovery evidence."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_db, require_owner
from models import RecoveryCeremony
from routers.vault import _get_vault
from services.audit import record_audit
from services.recovery_readiness import assignment_signature, recovery_evidence
from services.trigger_service import lock_status

router = APIRouter(prefix="/vault", dependencies=[Depends(require_owner)], tags=["readiness"])


@router.get("/readiness")
def readiness(user=Depends(require_owner), db=Depends(get_db)):
    vault = _get_vault(db, user)
    return recovery_evidence(db, vault)


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
