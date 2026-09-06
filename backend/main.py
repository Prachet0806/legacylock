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
from middleware.security import SecurityHeadersMiddleware
from routers import access, auth, beneficiaries, health, heartbeat, shares, stats, trigger, vault
from services.heartbeat_checker import check_heartbeat

settings = get_settings()

setup_logging()
logger = logging.getLogger("legacylock")

HEARTBEAT_CHECK_INTERVAL = int(os.environ.get("HEARTBEAT_CHECK_INTERVAL", "3600"))


async def _heartbeat_loop() -> None:
    """Background task that periodically checks heartbeat inactivity."""
    while True:
        await asyncio.sleep(HEARTBEAT_CHECK_INTERVAL)
        try:
            db = SessionLocal()
            try:
                result = check_heartbeat(db)
                if result:
                    logger.warning("Heartbeat check result: %s", result)
            finally:
                db.close()
        except Exception:
            logger.exception("Heartbeat check failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    task = asyncio.create_task(_heartbeat_loop())
    yield
    task.cancel()


app = FastAPI(title="LegacyLock API", lifespan=lifespan)

# Security headers FIRST (before CORS)
app.add_middleware(SecurityHeadersMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(vault.router)
app.include_router(beneficiaries.router)
app.include_router(heartbeat.router)
app.include_router(stats.router)
app.include_router(trigger.router)
app.include_router(shares.router)
app.include_router(shares.public_router)
app.include_router(access.public_router)
app.include_router(access.router)
app.include_router(access.owner_router)
