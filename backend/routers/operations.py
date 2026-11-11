import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from config import get_settings
from deps import get_db
from models import BusinessEvent, DeliveryAttempt, DeliveryJob, WorkerCheckpoint
from services.outbox import utc

router = APIRouter(prefix="/operations", tags=["operations"])


def _scheduler_detail(scheduler: dict | None) -> dict | None:
    if scheduler is None:
        return None
    return {
        "running": scheduler["running"],
        "started_at": scheduler["started_at"].isoformat(),
        "last_heartbeat_at": (
            scheduler["last_heartbeat_at"].isoformat()
            if scheduler["last_heartbeat_at"] else None
        ),
        "last_delivery_at": (
            scheduler["last_delivery_at"].isoformat()
            if scheduler["last_delivery_at"] else None
        ),
        "errors": scheduler["errors"],
    }


@router.get("/recovery")
def recovery_health(  # noqa: C901 - aggregates independent recovery signals
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    expected = get_settings().operations_token
    received = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not secrets.compare_digest(received, expected):
        raise HTTPException(401, "Not authenticated")
    now = datetime.now(UTC)
    settings = get_settings()
    max_checkpoint_age = (
        timedelta(seconds=settings.demo_check_interval_seconds * 2 + 120)
        if settings.task_mode == "single_process_demo"
        else timedelta(minutes=5)
    )
    reasons = []
    if get_settings().release_hold:
        reasons.append("release_hold")
    for kind in ("checker", "delivery"):
        row = db.get(WorkerCheckpoint, kind)
        if (
            not row
            or not row.last_success_at
            or utc(row.last_success_at) < now - max_checkpoint_age
            or row.last_error
        ):
            reasons.append(f"{kind}_degraded")
    counts = {
        state: db.query(DeliveryJob).filter_by(state=state).count()
        for state in ("READY", "RETRY_WAIT", "CLAIMED", "ACCEPTED", "DEAD", "CANCELLED")
    }
    lagged = (
        db.query(DeliveryJob)
        .filter(
            DeliveryJob.state.in_(["READY", "RETRY_WAIT"]),
            DeliveryJob.due_at < now - max_checkpoint_age,
        )
        .count()
    )
    if lagged:
        reasons.append("due_work_lag")
    if counts["DEAD"]:
        reasons.append("dead_delivery")
    expired_leases = (
        db.query(DeliveryJob)
        .filter(DeliveryJob.state == "CLAIMED", DeliveryJob.lease_until < now)
        .count()
    )
    if expired_leases:
        reasons.append("expired_delivery_lease")
    oldest_overdue = (
        db.query(func.min(DeliveryJob.due_at))
        .filter(
            DeliveryJob.state.in_(["READY", "RETRY_WAIT"]),
            DeliveryJob.due_at < now,
        )
        .scalar()
    )
    last_delivery_attempt = db.query(func.max(DeliveryAttempt.started_at)).scalar()
    oldest_release = (
        db.query(func.min(BusinessEvent.created_at))
        .join(DeliveryJob)
        .filter(
            BusinessEvent.kind == "released",
            DeliveryJob.state.in_(["READY", "CLAIMED", "RETRY_WAIT"]),
        )
        .scalar()
    )
    provider_outcomes = {
        str(outcome): count
        for outcome, count in db.query(DeliveryAttempt.outcome, func.count())
        .filter(DeliveryAttempt.started_at >= now - timedelta(days=1))
        .group_by(DeliveryAttempt.outcome)
    }
    scheduler = None
    if settings.task_mode == "single_process_demo":
        from services.demo_scheduler import scheduler_status

        scheduler = scheduler_status()
        if not scheduler or not scheduler["running"]:
            reasons.append("scheduler_stopped")
        elif scheduler["errors"]:
            reasons.append("scheduler_error")
    return JSONResponse(
        {
            "status": "degraded" if reasons else "healthy",
            "reasons": reasons,
            "job_counts": counts,
            "pending_deliveries": counts["READY"] + counts["RETRY_WAIT"] + counts["CLAIMED"],
            "oldest_overdue_delivery_seconds": (
                max(0, int((now - utc(oldest_overdue)).total_seconds()))
                if oldest_overdue else 0
            ),
            "last_delivery_attempt_at": (
                utc(last_delivery_attempt).isoformat() if last_delivery_attempt else None
            ),
            "lagged_jobs": lagged,
            "expired_leases": expired_leases,
            "oldest_pending_release_seconds": max(
                0, int((now - utc(oldest_release)).total_seconds())
            )
            if oldest_release
            else 0,
            "provider_attempt_outcomes_24h": provider_outcomes,
            "acceptance_is_delivery": False,
            "scheduler": _scheduler_detail(scheduler),
        },
        status_code=503 if reasons else 200,
    )
