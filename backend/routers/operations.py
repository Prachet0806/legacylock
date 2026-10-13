import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from starlette.responses import JSONResponse

from config import get_settings
from deps import get_db
from models import BusinessEvent, DeliveryAttempt, DeliveryJob, WorkerCheckpoint
from services.outbox import utc

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/recovery")
def recovery_health(request: Request, db=Depends(get_db)):
    expected = get_settings().operations_token
    received = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not secrets.compare_digest(received, expected):
        raise HTTPException(401, "Not authenticated")
    now = datetime.now(UTC)
    reasons = []
    if get_settings().release_hold:
        reasons.append("release_hold")
    for kind in ("checker", "delivery"):
        row = db.get(WorkerCheckpoint, kind)
        if (
            not row
            or not row.last_success_at
            or utc(row.last_success_at) < now - timedelta(minutes=5)
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
            DeliveryJob.due_at < now - timedelta(minutes=5),
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
    return JSONResponse(
        {
            "status": "degraded" if reasons else "healthy",
            "reasons": reasons,
            "job_counts": counts,
            "lagged_jobs": lagged,
            "expired_leases": expired_leases,
            "oldest_pending_release_seconds": max(
                0, int((now - utc(oldest_release)).total_seconds())
            )
            if oldest_release
            else 0,
            "provider_attempt_outcomes_24h": provider_outcomes,
            "acceptance_is_delivery": False,
        },
        status_code=503 if reasons else 200,
    )
