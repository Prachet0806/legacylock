"""Failure-oriented acceptance tests for the remediation contracts."""

import asyncio
import base64
import secrets
from datetime import UTC, datetime, timedelta

from db import SessionLocal
from models import (
    AuthChallenge,
    Beneficiary,
    BusinessEvent,
    DeliveryAttempt,
    DeliveryJob,
    HeartbeatConfig,
    Vault,
    VaultStatus,
)
from services.auth import decode_access_token
from services.notifications import DeliveryResult
from services.outbox import claim, deliver_one, enqueue, event, unprotect
from services.trigger_service import trigger_vault


def material(revision=0):
    return {
        "wrapped_vmk": base64.b64encode(b"k" * 40).decode(),
        "vmk_crypto_version": 1,
        "vmk_kdf_algorithm": "PBKDF2-SHA256",
        "vmk_kdf_salt": base64.b64encode(b"s" * 16).decode(),
        "vmk_kdf_parameters": {"iterations": 600000},
        "expected_revision": revision,
    }


def draft(client, auth, generation=None):
    return client.post(
        "/vault/recovery-ceremony",
        headers=auth,
        json={
            "expected_revision": 0,
            "recovery_threshold": 2,
            "recovery_total": 3,
            "recovery_generation": generation or secrets.token_hex(16),
            "initial_material": material(),
        },
    )


def empty_vault():
    with SessionLocal() as db:
        vault = db.query(Vault).one()
        vault.wrapped_vmk = None
        vault.material_revision = 0
        vault.recovery_status = "UNINITIALIZED"
        db.commit()


def test_setup_cannot_replace_existing_material(client, auth):
    original = client.get("/vault/crypto-material", headers=auth).json()
    assert draft(client, auth).status_code == 409
    assert client.get("/vault/crypto-material", headers=auth).json() == original


def test_draft_restart_finalization_and_historical_generation(client, auth):
    empty_vault()
    generation = secrets.token_hex(16)
    first = draft(client, auth, generation)
    assert first.status_code == 200
    assert client.get("/vault/crypto-material", headers=auth).json()["wrapped_vmk"] is None
    second = draft(client, auth)
    ident = second.json()["ceremony_id"]
    assert (
        client.post(
            f"/vault/recovery-ceremony/{first.json()['ceremony_id']}/finalize",
            headers=auth,
            json={"stored_indexes": [1, 2, 3]},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/vault/recovery-ceremony/{ident}/finalize",
            headers=auth,
            json={"stored_indexes": [1, 1, 3]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/vault/recovery-ceremony/{ident}/finalize",
            headers=auth,
            json={"stored_indexes": [1, 2, 3]},
        ).status_code
        == 200
    )
    assert draft(client, auth, generation).status_code == 409
    assert client.get("/vault/crypto-material", headers=auth).json()["material_revision"] == 1


def test_rewrap_is_complete_and_revision_checked(client, auth):
    assert client.put("/vault/crypto-material", headers=auth, json=material(1)).status_code == 200
    assert client.put("/vault/crypto-material", headers=auth, json=material(1)).status_code == 409
    broken = material(2)
    broken["wrapped_vmk"] = base64.b64encode(b"k" * 32).decode()
    assert client.put("/vault/crypto-material", headers=auth, json=broken).status_code == 422
    assert client.get("/vault/crypto-material", headers=auth).json()["material_revision"] == 2


def test_release_rollback_and_retry_have_one_event(client, auth):
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        db.add(
            Beneficiary(
                vault_id=vid, name="Ben", email="ben@example.com", invitation_status="accepted"
            )
        )
        db.commit()
        trigger_vault(db, vid, "manual")
        db.rollback()
        assert db.query(BusinessEvent).count() == 0
        assert db.query(DeliveryJob).count() == 0
        trigger_vault(db, vid, "manual")
        db.commit()
        trigger_vault(db, vid, "manual")
        db.commit()
        assert db.query(BusinessEvent).filter_by(kind="released").count() == 1
        assert db.query(DeliveryJob).count() == 1
        assert "recovery shares" in unprotect(db.query(DeliveryJob).one())["body"]


def test_stale_inactivity_observation_cannot_release_after_checkin(client, auth):
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        db.add(
            HeartbeatConfig(
                vault_id=vid,
                interval_days=1,
                grace_days=1,
                last_check_in=datetime.now(UTC) - timedelta(days=3),
            )
        )
        db.add(
            VaultStatus(
                vault_id=vid,
                state="grace",
                armed=True,
                grace_started_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
        db.commit()
        db.query(HeartbeatConfig).one()  # cache an obsolete observation
        assert client.post("/heartbeat/checkin", headers=auth).status_code == 200
        vs, already = trigger_vault(db, vid, "inactivity")
        db.commit()
        assert already and vs.state == "active"
        assert db.query(BusinessEvent).filter_by(kind="released").count() == 0


def test_worker_retries_actual_send_and_recovers_expired_lease(client, auth, monkeypatch):
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        job = enqueue(
            db, event(db, vid, "test", 1), "owner:1", "owner@example.com", "Test", "No secret"
        )
        db.commit()
        ident = job.id
        first = claim(db)[0]
        job = db.get(DeliveryJob, ident)
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        second = claim(db)[0]
        assert first[1] != second[1]
    calls = []

    async def failed(*args):
        calls.append(args[-1])
        return DeliveryResult(False, True, "email_outcome_uncertain")

    monkeypatch.setattr("services.notifications.deliver_email", failed)
    asyncio.run(deliver_one(*first, SessionLocal))
    assert not calls  # a stale worker cannot send or mark this claim
    asyncio.run(deliver_one(*second, SessionLocal))
    with SessionLocal() as db:
        job = db.get(DeliveryJob, ident)
        assert job.state == "RETRY_WAIT" and job.last_error == "email_outcome_uncertain"
        job.due_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        third = claim(db)[0]
    asyncio.run(deliver_one(*third, SessionLocal))
    with SessionLocal() as db:
        job = db.get(DeliveryJob, ident)
        assert job.state == "RETRY_WAIT"
        job.due_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        fourth = claim(db)[0]

    async def success(*args):
        calls.append(args[-1])
        return DeliveryResult(True, provider_id="provider-123")

    monkeypatch.setattr("services.notifications.deliver_email", success)
    asyncio.run(deliver_one(*fourth, SessionLocal))
    with SessionLocal() as db:
        job = db.get(DeliveryJob, ident)
        assert job.state == "ACCEPTED" and job.provider_id == "provider-123" and job.payload is None
        attempts = db.query(DeliveryAttempt).filter_by(job_id=ident).all()
        assert len(attempts) == 3  # the abandoned lease is not an actual send
        assert all(row.started_at and row.completed_at for row in attempts)
        assert {row.outcome for row in attempts} == {"email_outcome_uncertain", "accepted"}
    assert calls == [ident, ident, ident]


def test_provider_acceptance_from_stale_claim_cannot_overwrite_reclaimed_job(
    client, auth, monkeypatch
):
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        job = enqueue(
            db,
            event(db, vid, "stale_result", 1),
            "owner:1",
            "test@example.com",
            "Subject",
            "Synthetic",
        )
        db.commit()
        ident = job.id
        first = claim(db)[0]
    replacement = []

    async def reclaim_during_provider_call(*args):
        with SessionLocal() as db:
            row = db.get(DeliveryJob, ident)
            row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
            replacement.extend(claim(db))
        return DeliveryResult(True, provider_id="first-provider-acceptance")

    monkeypatch.setattr("services.notifications.deliver_email", reclaim_during_provider_call)
    asyncio.run(deliver_one(*first, SessionLocal))
    with SessionLocal() as db:
        row = db.get(DeliveryJob, ident)
        assert row.state == "CLAIMED" and row.claim_token == replacement[0][1]
        assert row.provider_id is None
        assert db.get(DeliveryAttempt, first[1]).outcome == "accepted"

    async def deduplicated(*args):
        assert args[-1] == ident  # provider receives the same stable idempotency key
        return DeliveryResult(True, provider_id="first-provider-acceptance")

    monkeypatch.setattr("services.notifications.deliver_email", deduplicated)
    asyncio.run(deliver_one(*replacement[0], SessionLocal))
    with SessionLocal() as db:
        assert db.get(DeliveryJob, ident).state == "ACCEPTED"


def test_fresh_browser_magic_link_single_use_and_contact_revocation(client, auth):
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        ben = Beneficiary(
            vault_id=vid, name="Ben", email="ben@example.com", invitation_status="accepted"
        )
        db.add(ben)
        db.commit()
        bid = ben.id
    client.cookies.clear()
    generic = client.post("/access/login/request", json={"email": "unknown@example.com"}).json()
    assert client.post("/access/login/request", json={"email": "ben@example.com"}).json() == generic
    with SessionLocal() as db:
        raw = unprotect(db.query(DeliveryJob).one())["body"].split("token=", 1)[1].split()[0]
        assert raw not in db.query(AuthChallenge).one().token_hash
    assert client.post("/access/login/redeem", json={"token": raw}).status_code == 200
    access = client.cookies.get("legacylock_beneficiary_session")
    assert client.get("/access/status").json()["vault_status"] == "active"
    assert client.get("/access/messages").status_code == 403
    assert client.post("/access/login/redeem", json={"token": raw}).status_code == 401
    assert (
        client.put(
            f"/beneficiaries/{bid}", headers=auth, json={"email": "replacement@example.com"}
        ).status_code
        == 200
    )
    assert (
        client.get("/access/status", headers={"Authorization": f"Bearer {access}"}).status_code
        == 401
    )


def test_owner_logout_revokes_access_immediately(client, auth):
    with SessionLocal() as db:
        email = db.query(Vault).one().owner.email
    client.cookies.clear()
    assert (
        client.post(
            "/auth/login", json={"email": email, "password": "TestPass123!Long"}
        ).status_code
        == 200
    )
    access = client.cookies.get("legacylock_owner_session")
    assert decode_access_token(access)["jti"]
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401


def test_payload_ciphertext_cannot_be_replayed_to_another_job(client, auth):
    import pytest

    from services.outbox import unprotect

    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        business = event(db, vid, "payload_test", 1)
        a = enqueue(db, business, "owner:1", "one@example.com", "Subject", "Credential")
        b = enqueue(db, business, "owner:2", "two@example.com", "Subject", "Other")
        db.flush()
        b.payload = a.payload
        with pytest.raises(Exception):
            unprotect(b)
        db.rollback()


def test_release_hold_preserves_checkin_and_auth_delivery(client, auth, monkeypatch):
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "release_hold", True)
    assert client.post("/heartbeat/checkin", headers=auth).status_code == 200
    assert (
        client.post(
            "/vault/trigger", headers=auth, json={"password": "TestPass123!Long", "confirm": True}
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        enqueue(db, event(db, vid, "released", 1), "owner:1", "one@example.com", "Release", "Held")
        allowed = enqueue(
            db,
            event(db, vid, "beneficiary_login", 1),
            "owner:1",
            "one@example.com",
            "Sign-in",
            "Allowed",
        )
        db.commit()
        ident = allowed.id
        assert [job_id for job_id, _ in claim(db)] == [ident]


def test_drill_evidence_invalidates_after_assignment_change(client, auth):
    empty_vault()
    created = draft(client, auth).json()
    ident = created["ceremony_id"]
    assert (
        client.post(
            f"/vault/recovery-ceremony/{ident}/finalize",
            headers=auth,
            json={"stored_indexes": [1, 2, 3]},
        ).status_code
        == 200
    )
    state = client.get("/vault/readiness", headers=auth).json()
    assert (
        state["initialized"] and not state["quorum_assigned"] and not state["owner_reported_drill"]
    )
    body = {
        "material_revision": state["material_revision"],
        "assignment_signature": state["assignment_signature"],
        "generation": state["generation"],
    }
    assert client.post("/vault/drill", headers=auth, json=body).status_code == 200
    assert client.get("/vault/readiness", headers=auth).json()["owner_reported_drill"]
    assert (
        client.post(
            "/beneficiaries", headers=auth, json={"name": "New", "email": "new@example.com"}
        ).status_code
        == 201
    )
    assert client.get("/vault/readiness", headers=auth).json()["owner_reported_drill"] is None
    assert client.post("/vault/drill", headers=auth, json=body).status_code == 409


def test_restore_quarantine_preserves_crypto_and_invalidates_credentials(client, auth, monkeypatch):
    from config import get_settings
    from ops import inventory, quarantine_restored_database

    settings = get_settings()
    monkeypatch.setattr(settings, "release_hold", True)
    monkeypatch.setattr(settings, "delivery_enabled", False)
    monkeypatch.setattr(settings, "auth_epoch", "restored-new-epoch")
    with SessionLocal() as db:
        before = inventory(db)["crypto_snapshot_sha256"]
        quarantine_restored_database(db, "initial")
        assert inventory(db)["crypto_snapshot_sha256"] == before
        from models import AuthSession

        assert all(row.revoked for row in db.query(AuthSession))
    assert client.get("/auth/me", headers=auth).status_code == 401


def test_credential_path_redaction_applies_to_uvicorn_arguments():
    import logging

    from logging_config import SensitiveDataFilter

    raw = "synthetic-credential-long-random"
    record = logging.LogRecord(
        "uvicorn.access",
        20,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "POST", f"/access/invite/{raw}/accept", "1.1", 200),
        None,
    )
    assert SensitiveDataFilter().filter(record)
    assert raw not in record.getMessage()


def test_recovery_degradation_does_not_disable_checkins_or_api_readiness(client, auth, monkeypatch):
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "operations_token", "isolated-operations-monitor")
    monkeypatch.setattr(settings, "release_hold", True)
    assert client.get("/operations/recovery").status_code == 401
    health = client.get(
        "/operations/recovery", headers={"Authorization": "Bearer isolated-operations-monitor"}
    )
    assert health.status_code == 503
    assert "release_hold" in health.json()["reasons"]
    assert "checker_degraded" in health.json()["reasons"]
    assert health.json()["acceptance_is_delivery"] is False
    assert client.get("/readyz").status_code == 200
    assert client.post("/heartbeat/checkin", headers=auth).status_code == 200
    status = client.get("/vault/status", headers=auth).json()
    assert status["release_hold"] and status["armed"]


def test_expired_payload_cleanup_retains_terminal_failure_evidence(client, auth):
    from services.outbox import work_once

    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        business = event(db, vid, "retention_test", 1)
        job = enqueue(
            db,
            business,
            "owner:1",
            "test@example.com",
            "Subject",
            "synthetic expired capability",
            expires=datetime.now(UTC) - timedelta(seconds=1),
        )
        job.state, job.last_error = "DEAD", "restore_reconcile"
        db.commit()
        ident = job.id
    work_once(SessionLocal, limit=0)
    with SessionLocal() as db:
        job = db.get(DeliveryJob, ident)
        assert job.payload is None
        assert job.state == "DEAD" and job.last_error == "restore_reconcile"
