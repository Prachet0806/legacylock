"""Audit service — persist AuditEvent rows + stdout log (metadata only, never secrets)."""

from sqlalchemy.orm import Session

from logging_config import log_audit
from models import AuditEvent


def record_audit(
    db: Session,
    vault_id: int,
    actor_type: str,
    actor_id: int,
    event_type: str,
    metadata: dict | None = None,
) -> None:
    safe_meta = dict(metadata or {})
    # Defense-in-depth: strip secret-ish keys even if a caller passes them.
    for k in list(safe_meta.keys()):
        lk = k.lower()
        if any(s in lk for s in ("password", "passphrase", "vmk", "mek", "kek", "share", "ciphertext", "token", "secret")):
            safe_meta[k] = "[REDACTED]"
    import json

    db.add(
        AuditEvent(
            vault_id=vault_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            event_metadata=json.dumps(safe_meta) if safe_meta else None,
        )
    )
    db.commit()
    try:
        log_audit(event_type, actor_type, actor_id, vault_id, **safe_meta)
    except Exception:
        pass
