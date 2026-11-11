import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Callable, TypeVar

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
settings.validate_production_api()

setup_logging()
logger = logging.getLogger("legacylock")

HEARTBEAT_CHECK_INTERVAL = int(os.environ.get("HEARTBEAT_CHECK_INTERVAL", "60"))
T = TypeVar("T")


def _startup_checked(check: str, operation: Callable[[], T]) -> T:
    """Log a fixed startup stage without exposing exception text or key material."""
    try:
        return operation()
    except Exception as exc:
        # The operational log filter intentionally redacts messages containing
        # words such as "jwt" and "secret". Keep check names free of those words.
        logger.error("STARTUP_CHECK_FAILED check=%s error_type=%s", check, type(exc).__name__)
        raise


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


async def _delivery_loop() -> None:
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

    private_pem = _startup_checked("signing_private_load", _get_jwt_private_key)
    public_pem = _startup_checked("signing_public_load", _get_jwt_public_key)
    from cryptography.hazmat.primitives import serialization

    private = _startup_checked(
        "signing_private_parse",
        lambda: serialization.load_pem_private_key(private_pem.encode(), password=None),
    )
    public = _startup_checked(
        "signing_public_parse",
        lambda: serialization.load_pem_public_key(public_pem.encode()),
    )
    try:
        if private.key_size < 2048 or private.public_key().public_numbers() != public.public_numbers():
            raise RuntimeError("JWT RSA key pair is invalid or mismatched")
    except Exception as exc:
        logger.error("STARTUP_CHECK_FAILED check=signing_pair error_type=%s", type(exc).__name__)
        raise
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
            logger.error("STARTUP_CHECK_FAILED check=mail_provider_config error_type=MissingValue")
            raise RuntimeError("RESEND_API_KEY required in production")
        from services.outbox import payload_key

        _startup_checked("delivery_cipher_load", payload_key)
    # In test env init_db creates tables; in prod Alembic owns schema.
    if settings.environment != "production" and not settings.migrated_schema_only:
        init_db()
    task = asyncio.create_task(_heartbeat_loop()) if settings.background_in_api else None
    delivery_task = (
        asyncio.create_task(_delivery_loop())
        if settings.environment != "test" and settings.background_in_api
        else None
    )
    demo_scheduler = None
    if settings.task_mode == "single_process_demo":
        from services.demo_scheduler import DemoScheduler

        demo_scheduler = _startup_checked("scheduler_construct", DemoScheduler)
        _startup_checked("scheduler_start", demo_scheduler.start)
    logger.info("STARTUP_CHECKS_PASSED")
    try:
        yield
    finally:
        if demo_scheduler:
            await demo_scheduler.stop()
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
    allow_methods=["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"],
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
