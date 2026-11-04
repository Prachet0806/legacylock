"""Sanitized inventory and explicit post-restore quarantine. Never sends mail.

Run from backend with the intended DATABASE_URL already in the environment.
The operator must stop both API and worker before a restored database is opened.
"""

import argparse
import base64
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import func, inspect, text

from config import get_settings
from db import SessionLocal
from models import (
    AuthChallenge,
    AuthSession,
    Beneficiary,
    BusinessEvent,
    DeliveryJob,
    EmailVerificationToken,
    HeartbeatConfig,
    NotificationLog,
    Vault,
    VaultMessage,
    VaultStatus,
)
from services.audit import record_audit
from services.outbox import enqueue, event
from services.trigger_service import lock_status


def inventory(db):
    schema_revision = (
        db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if inspect(db.bind).has_table("alembic_version")
        else None
    )
    digest = hashlib.sha256()
    anomalies = {
        "invalid_wrapped_key": 0,
        "invalid_message_envelope": 0,
        "oversized_existing_message": 0,
        "uninitialized_with_messages": 0,
        "schema_revision_mismatch": int(schema_revision != "0008_delivery_attempts"),
    }
    for vault in db.query(Vault).order_by(Vault.id).yield_per(100):
        bundle = [
            vault.id,
            vault.wrapped_vmk,
            vault.vmk_crypto_version,
            vault.vmk_kdf_algorithm,
            vault.vmk_kdf_salt,
            vault.vmk_kdf_parameters,
            vault.recovery_generation,
            vault.recovery_threshold,
            vault.recovery_total,
        ]
        digest.update(json.dumps(bundle, separators=(",", ":")).encode())
        if vault.wrapped_vmk:
            try:
                parameters = json.loads(vault.vmk_kdf_parameters)
                if (
                    len(base64.b64decode(vault.wrapped_vmk, validate=True)) != 40
                    or vault.vmk_crypto_version != 1
                    or vault.vmk_kdf_algorithm != "PBKDF2-SHA256"
                    or len(base64.b64decode(vault.vmk_kdf_salt, validate=True)) != 16
                    or not 100000 <= parameters["iterations"] <= 2000000
                ):
                    anomalies["invalid_wrapped_key"] += 1
            except (ValueError, TypeError, KeyError):
                anomalies["invalid_wrapped_key"] += 1
        elif db.query(VaultMessage.id).filter_by(vault_id=vault.id).first():
            anomalies["uninitialized_with_messages"] += 1
    for message in db.query(VaultMessage).order_by(VaultMessage.id).yield_per(100):
        digest.update(
            json.dumps(
                [
                    message.id,
                    message.vault_id,
                    message.ciphertext,
                    message.wrapped_mek,
                    message.crypto_version,
                    message.crypto_metadata,
                ],
                separators=(",", ":"),
            ).encode()
        )
        try:
            metadata = json.loads(message.crypto_metadata)
            ct = base64.b64decode(message.ciphertext, validate=True)
            if (
                message.crypto_version != 1
                or len(ct) < 16
                or len(base64.b64decode(message.wrapped_mek, validate=True)) != 40
                or len(base64.b64decode(metadata["iv"], validate=True)) != 12
            ):
                anomalies["invalid_message_envelope"] += 1
            if len(ct) > 1024 * 1024 + 16:
                anomalies["oversized_existing_message"] += 1
        except (ValueError, KeyError, TypeError):
            anomalies["invalid_message_envelope"] += 1

    def grouped(model, column):
        return {str(key): count for key, count in db.query(column, func.count()).group_by(column)}

    return {
        "schema_revision": schema_revision,
        "schema_contract": "0008_delivery_attempts",
        "vaults": db.query(Vault).count(),
        "messages": db.query(VaultMessage).count(),
        "beneficiaries": db.query(Beneficiary).count(),
        "armed_vaults": db.query(VaultStatus).filter_by(armed=True).count(),
        "configured_checkins": db.query(HeartbeatConfig)
        .filter(HeartbeatConfig.last_check_in.isnot(None))
        .count(),
        "assigned_recipients": db.query(Beneficiary)
        .filter(Beneficiary.share_index.isnot(None))
        .count(),
        "session_states": grouped(AuthSession, AuthSession.revoked),
        "invitation_states": grouped(Beneficiary, Beneficiary.invitation_status),
        "legacy_notification_states": grouped(NotificationLog, NotificationLog.status),
        "vault_states": grouped(VaultStatus, VaultStatus.state),
        "recovery_states": grouped(Vault, Vault.recovery_status),
        "delivery_states": grouped(DeliveryJob, DeliveryJob.state),
        "anomalies": anomalies,
        "crypto_snapshot_sha256": digest.hexdigest(),
    }


def quarantine_restored_database(db, previous_epoch):
    settings = get_settings()
    if (
        not settings.release_hold
        or settings.delivery_enabled
        or settings.auth_epoch in (previous_epoch, "initial")
    ):
        raise RuntimeError(
            "Requires RELEASE_HOLD=true, DELIVERY_ENABLED=false and a fresh AUTH_EPOCH"
        )
    now = datetime.now(UTC)
    db.query(AuthSession).update({"revoked": True}, synchronize_session=False)
    db.query(AuthChallenge).filter_by(consumed_at=None).update(
        {"consumed_at": now}, synchronize_session=False
    )
    db.query(EmailVerificationToken).delete(synchronize_session=False)
    for ben in db.query(Beneficiary).order_by(Beneficiary.vault_id, Beneficiary.id):
        ben.session_jti = ben.refresh_hash = ben.refresh_expires_at = ben.invitation_hash = None
        if ben.invitation_status == "sent":
            ben.invitation_status = "pending"
    for job in db.query(DeliveryJob).filter(
        DeliveryJob.state.in_(["READY", "CLAIMED", "RETRY_WAIT"])
    ):
        job.state, job.claim_token, job.lease_until, job.last_error = (
            "DEAD",
            None,
            None,
            "restore_reconcile",
        )
        if job.credential_expires_at:
            job.payload = None
    for vault in db.query(Vault).order_by(Vault.id):
        lock_status(db, vault.id)
        record_audit(db, vault.id, "system", 0, "restore.quarantine", {})
    db.commit()


def adopt_legacy_release_evidence(db):
    if not get_settings().release_hold:
        raise RuntimeError("Legacy cutover requires RELEASE_HOLD=true")
    count = 0
    for status in db.query(VaultStatus).filter_by(state="triggered").order_by(VaultStatus.vault_id):
        status = lock_status(db, status.vault_id)
        if db.query(BusinessEvent).filter_by(vault_id=status.vault_id, kind="released").first():
            continue
        business = event(db, status.vault_id, "released", status.version)
        for ben in db.query(Beneficiary).filter_by(
            vault_id=status.vault_id, invitation_status="accepted"
        ):
            job = enqueue(
                db,
                business,
                f"beneficiary:{ben.id}",
                ben.email,
                "LegacyLock - Release reconciliation",
                "Access was previously released. Sign in using your email and separately stored "
                "recovery shares.",
                beneficiary=ben,
            )
            job.state, job.last_error = "DEAD", "legacy_release_reconcile"
        record_audit(db, status.vault_id, "system", 0, "release.legacy_evidence_imported", {})
        count += 1
    db.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarantine-restored", action="store_true")
    parser.add_argument("--ack-isolated-restore", action="store_true")
    parser.add_argument("--previous-auth-epoch")
    parser.add_argument("--adopt-legacy-release-evidence", action="store_true")
    parser.add_argument(
        "--record-hold", action="store_true", help="Audit the deployed release-hold configuration"
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.quarantine_restored:
            if not args.ack_isolated_restore or not args.previous_auth_epoch:
                parser.error(
                    "Restore quarantine requires an isolated-restore acknowledgment and "
                    "previous epoch"
                )
            quarantine_restored_database(db, args.previous_auth_epoch)
        if args.adopt_legacy_release_evidence:
            adopt_legacy_release_evidence(db)
        if args.record_hold:
            for vault in db.query(Vault).order_by(Vault.id):
                lock_status(db, vault.id)
                record_audit(
                    db,
                    vault.id,
                    "system",
                    0,
                    "release.hold.configured",
                    {"held": get_settings().release_hold},
                )
            db.commit()
        print(json.dumps(inventory(db), indent=2))


if __name__ == "__main__":
    main()
