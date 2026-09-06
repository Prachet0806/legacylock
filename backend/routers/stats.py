from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import Beneficiary, HeartbeatConfig, VaultMessage, VaultStatus
from deps import get_db, require_owner

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(require_owner)],
)


class StatsOut(BaseModel):
    message_count: int
    beneficiary_count: int
    last_check_in: str | None
    heartbeat_interval: int | None
    heartbeat_grace: int | None
    vault_status: str


@router.get("", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    msg_count = db.query(VaultMessage).count()
    ben_count = db.query(Beneficiary).count()

    hb = db.query(HeartbeatConfig).first()
    vs = db.query(VaultStatus).first()

    return StatsOut(
        message_count=msg_count,
        beneficiary_count=ben_count,
        last_check_in=hb.last_check_in.isoformat() if hb and hb.last_check_in else None,
        heartbeat_interval=hb.interval_days if hb else None,
        heartbeat_grace=hb.grace_days if hb else None,
        vault_status=vs.state if vs else "active",
    )