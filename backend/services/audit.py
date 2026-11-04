"""Stage durable AuditEvent rows in the caller's transaction; never emit secrets."""

from sqlalchemy.orm import Session

from models import AuditEvent


def record_audit(
    db: Session,
    vault_id: int | None,
    actor_type: str,
    actor_id: int,
    event_type: str,
    metadata: dict | None = None,
) -> None:
    """Stage an audit row on the caller's session — add-only, no commit.

    The caller owns the single commit, so the domain mutation and its audit
    row land atomically together (or neither lands on rollback).
    """
    safe_meta = dict(metadata or {})
    # Defense-in-depth: strip secret-ish keys even if a caller passes them.
    for k in list(safe_meta.keys()):
        lk = k.lower()
        if any(
            s in lk
            for s in (
                "password",
                "passphrase",
                "vmk",
                "mek",
                "kek",
                "share",
                "ciphertext",
                "token",
                "secret",
            )
        ):
            safe_meta[k] = "[REDACTED]"
    import json

    from services.request_ctx import current_client_ip, current_request_id

    db.add(
        AuditEvent(
            vault_id=vault_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            event_metadata=json.dumps(safe_meta) if safe_meta else None,
            request_id=current_request_id(),
            ip_address=current_client_ip(),
        )
    )
    db.flush()
    # The database transaction is authoritative. Avoid pre-commit stdout
    # claims that could survive a rollback.
