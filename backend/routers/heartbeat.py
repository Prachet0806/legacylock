from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_owner
from logging_config import log_audit
from models import HeartbeatConfig, User, Vault, VaultStatus

router = APIRouter(
    prefix="/heartbeat",
    tags=["heartbeat"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_vault(db: Session, current_user: User) -> Vault:
    """Get the vault for the current owner."""
    vault = (
        db.query(Vault).filter(Vault.user_id == current_user.id, Vault.is_primary == True).first()
    )
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    return vault


def _get_or_create_heartbeat_config(db: Session, vault_id: int) -> HeartbeatConfig:
    """Return the config row for a specific vault, creating it with defaults if absent."""
    cfg = db.query(HeartbeatConfig).filter(HeartbeatConfig.vault_id == vault_id).first()
    if not cfg:
        cfg = HeartbeatConfig(vault_id=vault_id, interval_days=30, grace_days=7)
        db.add(cfg)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            cfg = db.query(HeartbeatConfig).filter(HeartbeatConfig.vault_id == vault_id).first()
            if not cfg:
                raise
            return cfg
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


class RunCheckIn(BaseModel):
    # Days of simulated elapsed time for deterministic E2E (time travel).
    # advance_days=31 on a 30-day interval behaves as if 31 days passed.
    advance_days: float = Field(0, ge=0, le=3650)


class RunCheckOut(BaseModel):
    actions: list[str]
    simulated_now: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=HeartbeatOut)
def get_heartbeat(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    cfg = _get_or_create_heartbeat_config(db, vault.id)
    return HeartbeatOut(
        interval_days=cfg.interval_days,
        grace_days=cfg.grace_days,
        last_check_in=cfg.last_check_in.isoformat() if cfg.last_check_in else None,
        updated_at=cfg.updated_at.isoformat() if cfg.updated_at else "",
    )


@router.put("")
def save_heartbeat(
    data: HeartbeatSettingsIn,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if data.grace_days > data.interval_days:
        raise HTTPException(status_code=422, detail="grace_days should not exceed interval_days")
    vault = _get_vault(db, current_user)
    cfg = _get_or_create_heartbeat_config(db, vault.id)
    cfg.interval_days = data.interval_days
    cfg.grace_days = data.grace_days
    cfg.updated_at = datetime.now(UTC)
    db.commit()
    try:
        log_audit("heartbeat.save", "owner", current_user.id, vault.id)
    except Exception:
        pass
    return {"message": "Heartbeat settings saved"}


@router.post("/checkin")
def check_in(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    cfg = _get_or_create_heartbeat_config(db, vault.id)
    now = datetime.now(UTC)
    cfg.last_check_in = now
    cfg.updated_at = now
    # Single transaction: check-in timestamp AND grace-cancel CAS-reset commit
    # together, so a crash between them can't split the state.
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    if vs and vs.state != "triggered" and (vs.state != "active" or vs.grace_started_at is not None):
        ver = vs.version or 1
        # A concurrent auto-trigger that already committed wins; a stale one
        # loses its version check.
        db.query(VaultStatus).filter(
            VaultStatus.id == vs.id,
            VaultStatus.version == ver,
            VaultStatus.state != "triggered",
        ).update(
            {"state": "active", "grace_started_at": None, "version": ver + 1, "updated_at": now},
            synchronize_session="fetch",
        )
    try:
        log_audit("heartbeat.checkin", "owner", current_user.id, vault.id)
    except Exception:
        pass
    db.commit()
    return {"message": "Check-in recorded", "last_check_in": cfg.last_check_in.isoformat()}


@router.post("/run-check", response_model=RunCheckOut)
def run_check(
    data: RunCheckIn,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Run the heartbeat checker synchronously with optional time travel.

    Non-production only (404 in production, like POST /vault/reset-status).
    Lets E2E prove ACTIVE → GRACE → TRIGGERED with realistic day-granularity
    config (e.g. 30/7) instead of waiting out real deadlines. Production
    behavior is untouched: the background loop calls check_heartbeat(db)
    with no `now` override.
    """
    if get_settings().environment == "production":
        raise HTTPException(status_code=404, detail="Not found")
    from services.heartbeat_checker import check_heartbeat

    now = datetime.now(UTC) + timedelta(days=data.advance_days)
    actions = check_heartbeat(db, now=now)
    try:
        log_audit("heartbeat.run_check", "owner", current_user.id, None)
    except Exception:
        pass
    return RunCheckOut(actions=actions, simulated_now=now.isoformat())
