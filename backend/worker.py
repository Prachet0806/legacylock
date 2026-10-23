"""Independent worker. Run with BACKGROUND_IN_API=false on the API process."""

import logging
import time

from config import get_settings
from db import SessionLocal
from services.heartbeat_checker import check_heartbeat
from services.operations import checkpoint
from services.outbox import payload_key, work_once


def main():
    settings = get_settings()
    settings.validate_production()
    payload_key()
    if settings.environment == "production" and not settings.resend_api_key:
        raise RuntimeError("Email credentials required")
    next_check = 0.0
    delivery_failures = 0
    while True:
        if time.monotonic() >= next_check and settings.heartbeat_enabled:
            try:
                with SessionLocal() as db:
                    check_heartbeat(db)
                checkpoint(SessionLocal, "checker")
            except Exception as exc:
                _record_failure("checker", exc)
            next_check = time.monotonic() + 60
        try:
            work_once(SessionLocal)
            checkpoint(SessionLocal, "delivery")
            delivery_failures = 0
        except Exception as exc:
            _record_failure("delivery", exc)
            delivery_failures = min(delivery_failures + 1, 4)
        time.sleep(min(5 * (2 ** delivery_failures), 60))


def _record_failure(component: str, exc: Exception) -> None:
    logging.error("%s pass failed: %s", component, type(exc).__name__)
    try:
        checkpoint(SessionLocal, component, type(exc).__name__)
    except Exception:
        logging.exception("Could not persist %s failure checkpoint", component)


if __name__ == "__main__":
    main()
