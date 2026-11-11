from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.head("/health", include_in_schema=False)
def health_head() -> Response:
    return Response(status_code=200)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/scheduler-health")
def scheduler_health() -> JSONResponse:
    """Database-free liveness for the optional in-process demo scheduler."""
    settings = get_settings()
    if settings.task_mode != "single_process_demo":
        return JSONResponse({"status": "not_configured"}, status_code=404)
    from services.demo_scheduler import scheduler_status

    state = scheduler_status()
    max_age = timedelta(seconds=settings.demo_check_interval_seconds * 2 + 120)
    healthy = bool(
        state
        and state["running"]
        and state["last_heartbeat_at"]
        and state["last_delivery_at"]
        and not state["errors"]
        and datetime.now(UTC) - state["last_heartbeat_at"] < max_age
        and datetime.now(UTC) - state["last_delivery_at"] < max_age
    )
    return JSONResponse(
        {"status": "ok" if healthy else "degraded"},
        status_code=200 if healthy else 503,
    )
