from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import HeartbeatConfig
from deps import get_db, require_owner

router = APIRouter(
    prefix="/heartbeat",
    tags=["heartbeat"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create(db: Session) -> HeartbeatConfig:
    """Return the singleton config row, creating it with defaults if absent."""
    cfg = db.query(HeartbeatConfig).first()
    if not cfg:
        cfg = HeartbeatConfig(interval_days=30, grace_days=7)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class HeartbeatSettingsIn(BaseModel):
    interval_days: int = Field(..., ge=1, le=365)
    grace_days: int = Field(..., ge=1, le=90)


class HeartbeatOut(BaseModel):
    interval_days: int
    grace_days: int
    last_check_in: str | None
    updated_at: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=HeartbeatOut)
def get_heartbeat(db: Session = Depends(get_db)):
    cfg = _get_or_create(db)
    return HeartbeatOut(
        interval_days=cfg.interval_days,
        grace_days=cfg.grace_days,
        last_check_in=cfg.last_check_in.isoformat() if cfg.last_check_in else None,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else "",
    )


@router.put("")
def save_heartbeat(data: HeartbeatSettingsIn, db: Session = Depends(get_db)):
    cfg = _get_or_create(db)
    cfg.interval_days = data.interval_days
    cfg.grace_days = data.grace_days
    cfg.updated_at = datetime.now(UTC)
    db.commit()
    return {"message": "Heartbeat settings saved"}


@router.post("/checkin")
def check_in(db: Session = Depends(get_db)):
    cfg = _get_or_create(db)
    cfg.last_check_in = datetime.now(UTC)
    cfg.updated_at = datetime.now(UTC)
    db.commit()
    return {"message": "Check-in recorded", "last_check_in": cfg.last_check_in.isoformat()}