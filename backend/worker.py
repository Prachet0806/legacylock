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
    payload_key()
    if settings.environment == "production" and not settings.resend_api_key:
        raise RuntimeError("Email credentials required")
    next_check = 0.0
    while True:
        if time.monotonic() >= next_check and settings.heartbeat_enabled:
            try:
                with SessionLocal() as db:
                    check_heartbeat(db)
                checkpoint(SessionLocal, "checker")
            except Exception as exc:
                checkpoint(SessionLocal, "checker", type(exc).__name__)
                logging.error("Heartbeat pass failed: %s", type(exc).__name__)
            next_check = time.monotonic() + 60
        try:
            work_once(SessionLocal)
            checkpoint(SessionLocal, "delivery")
        except Exception as exc:
            checkpoint(SessionLocal, "delivery", type(exc).__name__)
            logging.error("Delivery pass failed: %s", type(exc).__name__)
        time.sleep(5)


if __name__ == "__main__":
    main()
