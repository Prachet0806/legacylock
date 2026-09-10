import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from db import SessionLocal, init_db
from logging_config import setup_logging
from middleware import RateLimiterMiddleware, RequestIdMiddleware, SecurityHeadersMiddleware
from routers import access, auth, beneficiaries, health, heartbeat, stats, trigger, vault
from services.heartbeat_checker import check_heartbeat

settings = get_settings()

setup_logging()
logger = logging.getLogger("legacylock")

HEARTBEAT_CHECK_INTERVAL = int(os.environ.get("HEARTBEAT_CHECK_INTERVAL", "3600"))


def _parse_origins(raw: str) -> list[str]:
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    # Never allow wildcard with credentials
    origins = [o for o in origins if o != "*"]
    if not origins:
        return ["http://localhost:3000"]
    return origins


async def _heartbeat_loop() -> None:
    """Background task that periodically checks heartbeat inactivity (in-process)."""
    # Run blocking DB work in a thread so the event loop stays responsive
    while True:
        await asyncio.sleep(HEARTBEAT_CHECK_INTERVAL)
        if not get_settings().heartbeat_enabled:
            continue
        try:
            def _run() -> list[str]:
                db = SessionLocal()
                try:
                    return check_heartbeat(db)
                finally:
                    db.close()

            results = await asyncio.to_thread(_run)
            for result in results:
                logger.info("Heartbeat check result: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heartbeat check failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Fail closed on bad keys before serving traffic (invalidates old tokens)
    from services.auth import _get_jwt_private_key, _get_jwt_public_key

    _get_jwt_private_key()
    _get_jwt_public_key()
    # In test env init_db creates tables; in prod Alembic owns schema.
    if settings.environment != "production":
        init_db()
    task = asyncio.create_task(_heartbeat_loop())
    yield
    task.cancel()


app = FastAPI(title="LegacyLock API", lifespan=lifespan)

# NOTE: Starlette executes middleware outermost-first in reverse-addition order
# (last added = outermost). So add innermost first, CORS last.
# Security headers (innermost)
app.add_middleware(SecurityHeadersMiddleware)

# Request ID for correlation
app.add_middleware(RequestIdMiddleware)

# Rate limiting
app.add_middleware(RateLimiterMiddleware, requests_per_minute=60, requests_per_hour=1000)

# CORS outermost so preflights are handled before auth/rate-limit logic
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

# Register routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(vault.router)
app.include_router(beneficiaries.router)
app.include_router(heartbeat.router)
app.include_router(stats.router)
app.include_router(trigger.router)
app.include_router(access.public_router)
app.include_router(access.router)
app.include_router(access.owner_router)
