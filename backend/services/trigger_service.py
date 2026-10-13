"""One transactional authority for release and its complete delivery intent."""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from config import get_settings
from models import Beneficiary, BusinessEvent, HeartbeatConfig, User, Vault, VaultStatus
from services.audit import record_audit
from services.outbox import cancel_warnings, enqueue, event, utc


def lock_status(db, vault_id):
    row = (
        db.query(VaultStatus)
        .filter_by(vault_id=vault_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if row is None:
        try:
            with db.begin_nested():
                row = VaultStatus(
                    vault_id=vault_id, state="active", version=1, armed=False, episode=0
                )
                db.add(row)
                db.flush()
        except IntegrityError:
            row = (
                db.query(VaultStatus)
                .filter_by(vault_id=vault_id)
                .populate_existing()
                .with_for_update()
                .one()
            )
    changed = (
        db.query(VaultStatus)
        .filter_by(id=row.id)
        .update({"version": VaultStatus.version + 1}, synchronize_session=False)
    )
    if not changed:
        raise HTTPException(409, "Vault changed; retry the operation")
    db.refresh(row)
    return row


def release_locked(db, vs, reason, now, actor_type="system", actor_id=0):
    if vs.state == "triggered":
        return vs, True
    if get_settings().release_hold:
        raise HTTPException(409, "Release is held for reconciliation")
    vs.state, vs.triggered_at, vs.trigger_reason, vs.updated_at = "triggered", now, reason, now
    cancel_warnings(db, vs.vault_id)
    business = event(db, vs.vault_id, "released", vs.version)
    for ben in (
        db.query(Beneficiary).filter_by(vault_id=vs.vault_id, invitation_status="accepted").all()
    ):
        enqueue(
            db,
            business,
            f"beneficiary:{ben.id}",
            ben.email,
            "LegacyLock — Vault Access Released",
            f"Vault access is now released. Sign in at {get_settings().frontend_origin()}/access/login and use the recovery shares already distributed to you. LegacyLock does not send or store shares.",
            beneficiary=ben,
        )
        if get_settings().sms_enabled and ben.phone:
            enqueue(
                db,
                business,
                f"beneficiary:{ben.id}",
                ben.phone,
                "",
                "LegacyLock vault access is released. Sign in using your email; use your separately stored shares.",
                beneficiary=ben,
                channel="sms",
            )
    record_audit(
        db,
        vs.vault_id,
        actor_type,
        actor_id,
        "vault.trigger",
        {"reason": reason, "revision": vs.version},
    )
    return vs, False


def trigger_vault(db, vault_id, reason, now=None, actor_type="system", actor_id=0):
    now = now or datetime.now(UTC)
    vs = lock_status(db, vault_id)
    if reason == "inactivity":
        cfg = db.query(HeartbeatConfig).filter_by(vault_id=vault_id).populate_existing().first()
        if not cfg or not cfg.last_check_in or not vs.armed or vs.state != "grace":
            return vs, True
        if now < utc(cfg.last_check_in) + timedelta(days=cfg.interval_days + cfg.grace_days):
            return vs, True
    return release_locked(db, vs, reason, now, actor_type, actor_id)


def move_to_grace(db, vault_id, now=None):
    now = now or datetime.now(UTC)
    vs = lock_status(db, vault_id)
    cfg = db.query(HeartbeatConfig).filter_by(vault_id=vault_id).populate_existing().first()
    if vs.state != "active" or not vs.armed or not cfg or not cfg.last_check_in:
        return vs, True
    deadline = utc(cfg.last_check_in) + timedelta(days=cfg.interval_days)
    if now < deadline:
        return vs, True
    vs.state, vs.grace_started_at, vs.updated_at = "grace", deadline, now
    vs.episode += 1
    record_audit(db, vault_id, "system", 0, "heartbeat.grace", {"episode": vs.episode})
    return vs, False


def stage_warning(db, vs, cfg, now):
    end = utc(cfg.last_check_in) + timedelta(days=cfg.interval_days + cfg.grace_days)
    remaining = (end - now).total_seconds()
    if remaining <= 0:
        return
    elapsed = (now - utc(vs.grace_started_at)).total_seconds() / 86400
    kinds = ["grace_first"]
    if elapsed >= 3 and cfg.grace_days > 3:
        kinds.append("grace_second")
    if remaining <= 86400:
        kinds.append("grace_final")
    vault = db.get(Vault, vs.vault_id)
    owner = db.get(User, vault.user_id)
    for kind in kinds:
        if (
            db.query(BusinessEvent.id)
            .filter_by(vault_id=vs.vault_id, kind=kind, revision=vs.episode)
            .first()
        ):
            continue
        business = event(db, vs.vault_id, kind, vs.episode)
        text = f"Check-in is overdue. The release deadline is {end.isoformat()}. The owner can cancel release by checking in before that deadline. Shares remain where you stored them."
        enqueue(
            db, business, f"owner:{owner.id}", owner.email, "LegacyLock — Check-in overdue", text
        )
        for ben in (
            db.query(Beneficiary)
            .filter_by(vault_id=vs.vault_id, invitation_status="accepted")
            .all()
        ):
            enqueue(
                db,
                business,
                f"beneficiary:{ben.id}",
                ben.email,
                "LegacyLock — Release deadline approaching",
                text,
                beneficiary=ben,
            )
