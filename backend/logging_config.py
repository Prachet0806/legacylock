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
        "password",
        "passphrase",
        "vmk",
        "mek",
        "kek",
        "session_secret",
        "jwt",
        "token",
        "cookie",
        "authorization",
        "invitation",
        "database_url",
        "secret",
    }

    def _redact_value(self, value: object) -> object:
        if isinstance(value, str):
            lowered = value.lower()
            for key in self.SENSITIVE_KEYS:
                if key in lowered:
                    return "[REDACTED]"
            # Redact email-like and long base64 blobs
            if "@" in value and "." in value and len(value) < 320:
                return "[REDACTED-EMAIL]"
            return value
        if isinstance(value, dict):
            return {
                k: ("[REDACTED]" if k.lower() in self.SENSITIVE_KEYS else self._redact_value(v))
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return type(value)(self._redact_value(v) for v in value)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            lowered = record.msg.lower()
            for key in self.SENSITIVE_KEYS:
                if key in lowered:
                    record.msg = "[REDACTED]"
                    record.args = ()
                    break
        if record.args:
            try:
                record.args = (
                    tuple(self._redact_value(a) for a in record.args)
                    if isinstance(record.args, tuple)
                    else self._redact_value(record.args)
                )
            except Exception:
                record.args = ()
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
            try:
                log_data["actor_id"] = int(getattr(record, "actor_id", 0) or 0)
            except (TypeError, ValueError):
                log_data["actor_id"] = 0
            log_data["vault_id"] = getattr(record, "vault_id", None)
            # Include extra metadata (excluding reserved LogRecord attrs)
            reserved = {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "audit",
                "event_type",
                "actor_type",
                "actor_id",
                "vault_id",
                "message",
            }
            for k, v in record.__dict__.items():
                if k not in reserved and not k.startswith("_"):
                    try:
                        json.dumps(v)
                        log_data[k] = v
                    except (TypeError, ValueError):
                        log_data[k] = str(v)
        # request correlation id if present
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_data["request_id"] = request_id
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
    event_type: str, actor_type: str, actor_id: int, vault_id: int | None = None, **metadata: Any
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
            **metadata,
        },
    )
