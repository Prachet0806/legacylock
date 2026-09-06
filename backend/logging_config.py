import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class AuditFilter(logging.Filter):
    """Filter to separate audit logs from operational logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "audit", False)


class OperationalFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "audit", False)


class SensitiveDataFilter(logging.Filter):
    """Redact sensitive fields from log records. Defense-in-depth only."""
    SENSITIVE_KEYS = {
        "password", "passphrase", "vmk", "mek", "kek",
        "session_secret", "jwt", "token", "cookie",
        "authorization", "invitation",
        "database_url", "secret",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            for key in self.SENSITIVE_KEYS:
                if key in record.msg.lower():
                    record.msg = "[REDACTED]"
                    break
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "audit"):
            log_data["audit"] = record.audit
            log_data["event_type"] = str(getattr(record, "event_type", "") or "")
            log_data["actor_type"] = str(getattr(record, "actor_type", "") or "")
            log_data["actor_id"] = int(getattr(record, "actor_id", 0) or 0)
            log_data["vault_id"] = getattr(record, "vault_id", None)
        return json.dumps(log_data)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)

    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(logging.INFO)
    audit_handler = logging.StreamHandler(sys.stdout)
    audit_handler.setFormatter(JSONFormatter())
    audit_handler.addFilter(AuditFilter())
    audit_logger.addHandler(audit_handler)
    audit_logger.propagate = False


def log_audit(
    event_type: str,
    actor_type: str,
    actor_id: int,
    vault_id: int | None = None,
    **metadata: Any
) -> None:
    logger = logging.getLogger("audit")
    logger.info(
        event_type,
        extra={
            "audit": True,
            "event_type": event_type,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "vault_id": vault_id,
            **metadata
        }
    )
