import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import get_settings
from db import SessionLocal, init_db
from logging_config import setup_logging
from middleware import (
    OriginCheckMiddleware,
    RateLimiterMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from middleware.body_limit import BodyLimitMiddleware
from routers import (
    access,
    auth,
    beneficiaries,
    beneficiary_login,
    health,
    heartbeat,
    operations,
    readiness,
    stats,
    trigger,
    vault,
)
from services.heartbeat_checker import check_heartbeat
from services.operations import checkpoint

settings = get_settings()
settings.validate_production()

setup_logging()
logger = logging.getLogger("legacylock")

HEARTBEAT_CHECK_INTERVAL = int(os.environ.get("HEARTBEAT_CHECK_INTERVAL", "60"))


async def _record_failure(component: str, exc: Exception) -> None:
    try:
        await asyncio.to_thread(checkpoint, SessionLocal, component, type(exc).__name__)
    except Exception:
        logger.exception("Could not persist %s failure checkpoint", component)


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
        if not get_settings().heartbeat_enabled or not get_settings().background_in_api:
            continue
        try:

            def _run() -> list[str]:
                db = SessionLocal()
                try:
                    return check_heartbeat(db)
                finally:
                    db.close()

            results = await asyncio.to_thread(_run)
            await asyncio.to_thread(checkpoint, SessionLocal, "checker")
            for result in results:
                logger.info("Heartbeat check result: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _record_failure("checker", exc)
            logger.exception("Heartbeat check failed")


async def _delivery_loop():
    from services.outbox import work_once

    while True:
        try:
            await asyncio.to_thread(work_once, SessionLocal)
            await asyncio.to_thread(checkpoint, SessionLocal, "delivery")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _record_failure("delivery", exc)
            logger.exception("Delivery worker pass failed")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Fail closed on bad keys before serving traffic (invalidates old tokens)
    from services.auth import _get_jwt_private_key, _get_jwt_public_key

    _get_jwt_private_key()
    _get_jwt_public_key()
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(settings.jwt_private_key().encode(), password=None)
    public = serialization.load_pem_public_key(settings.jwt_public_key().encode())
    if private.key_size < 2048 or private.public_key().public_numbers() != public.public_numbers():
        raise RuntimeError("JWT RSA key pair is invalid or mismatched")
    if settings.environment == "production":
        # Deployment discipline: X-Forwarded-For is trusted ONLY via
        # TRUSTED_PROXIES. An empty list behind a proxy makes client IPs
        # (and rate-limit buckets) attacker-controlled — warn loudly.
        if not settings.trusted_proxy_list():
            logger.warning(
                "TRUSTED_PROXIES empty in production: X-Forwarded-For ignored, "
                "rate limiting uses direct peer IP; set TRUSTED_PROXIES if behind "
                "Caddy/Cloudflare"
            )
        if not settings.resend_api_key:
            raise RuntimeError("RESEND_API_KEY required in production")
        from services.outbox import payload_key

        payload_key()
    # In test env init_db creates tables; in prod Alembic owns schema.
    if settings.environment != "production" and not settings.migrated_schema_only:
        init_db()
    task = asyncio.create_task(_heartbeat_loop()) if settings.background_in_api else None
    delivery_task = (
        asyncio.create_task(_delivery_loop())
        if settings.environment != "test" and settings.background_in_api
        else None
    )
    yield
    if task:
        task.cancel()
    if delivery_task:
        delivery_task.cancel()
    await asyncio.gather(
        *([task] if task else []),
        *([delivery_task] if delivery_task else []),
        return_exceptions=True,
    )


app = FastAPI(title="LegacyLock API", lifespan=lifespan)

# NOTE: Starlette executes middleware outermost-first in reverse-addition order
# (last added = outermost). So add innermost first, CORS last.
# Security headers (innermost)
app.add_middleware(SecurityHeadersMiddleware)

# Request ID for correlation
app.add_middleware(RequestIdMiddleware)

# Rate limiting
app.add_middleware(RateLimiterMiddleware, requests_per_minute=60, requests_per_hour=1000)

# CSRF origin check for cookie-authed mutations (inside CORS so preflights pass first)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
)

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
app.include_router(readiness.router)
app.include_router(operations.router)
app.include_router(beneficiaries.router)
app.include_router(heartbeat.router)
app.include_router(stats.router)
app.include_router(trigger.router)
app.include_router(access.public_router)
app.include_router(beneficiary_login.router)
app.include_router(access.router)
app.include_router(access.owner_router)
