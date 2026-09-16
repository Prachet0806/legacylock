"""Cross-tenant isolation, session isolation, and DB zero-knowledge checks."""

import base64
import uuid

import pytest

TRIGGER_BODY = {"password": "TestPass123!Long", "confirm": True}
RESET_BODY = {"password": "TestPass123!Long", "confirm": True}
_WMEK = base64.b64encode(b"0" * 32).decode()
_CT = base64.b64encode(b"x" * 16).decode()


def _owner(client, email):
    """Second owner independent of the auth fixture (returns headers)."""
    from db import SessionLocal
    from models import User, Vault
    from services.auth import create_access_token, hash_password

    db = SessionLocal()
    try:
        user = User(email=email, password_hash=hash_password("TestPass123!Long"))
        db.add(user)
        db.commit()
        db.refresh(user)
        vault = Vault(user_id=user.id, name="Primary Vault", is_primary=True)
        db.add(vault)
        db.commit()
        db.refresh(vault)
        uid, vid = user.id, vault.id
    finally:
        db.close()
    token = create_access_token(uid, vid, role="owner")
    return {"Authorization": f"Bearer {token}"}


def _beneficiary_of(client, owner_headers, name="Ben", email=None):
    """Create+invite+accept a beneficiary; return (beneficiary headers, raw invite)."""
    from db import SessionLocal
    from models import Beneficiary
    from services.auth import BENEFICIARY_TOKEN_EXPIRE_MINUTES, create_access_token

    email = email or f"{uuid.uuid4().hex[:8]}@t.com"
    ben_id = client.post(
        "/beneficiaries", json={"name": name, "email": email}, headers=owner_headers
    ).json()["id"]
    link = client.post(f"/beneficiaries/{ben_id}/invite", headers=owner_headers).json()[
        "invitation_link"
    ]
    raw = link.rsplit("/", 1)[-1]
    accepted = client.post(f"/access/invite/{raw}/accept")
    assert accepted.status_code == 200
    ben_db_id = accepted.json()["beneficiary_id"]
    db = SessionLocal()
    try:
        b = db.query(Beneficiary).filter(Beneficiary.id == ben_db_id).first()
        assert b is not None
        token = create_access_token(
            b.id, b.vault_id, role="beneficiary",
            expires_minutes=BENEFICIARY_TOKEN_EXPIRE_MINUTES,
        )
    finally:
        db.close()
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}, raw


class TestCrossTenantIsolation:
    def test_beneficiary_cannot_reach_other_vault(self, client, auth):
        other = _owner(client, f"other-{uuid.uuid4().hex[:8]}@example.com")
        other_mid = client.post(
            "/vault/messages",
            json={"label": "other-secret", "ciphertext": _CT, "wrapped_mek": _WMEK},
            headers=other,
        ).json()["id"]
        own_mid = client.post(
            "/vault/messages",
            json={"label": "own-secret", "ciphertext": _CT, "wrapped_mek": _WMEK},
            headers=auth,
        ).json()["id"]
        bh, _ = _beneficiary_of(client, auth)
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            rows = client.get("/access/messages", headers=bh).json()
            assert [r["id"] for r in rows] == [own_mid]
            assert client.get(f"/access/messages/{other_mid}", headers=bh).status_code == 404
            assert client.get(f"/access/messages/{own_mid}", headers=bh).status_code == 200
        finally:
            client.post("/vault/reset-status", json=RESET_BODY, headers=auth)
            client.post("/vault/reset-status", json=RESET_BODY, headers=other)


class TestSessionIsolation:
    def test_beneficiary_cannot_call_owner_endpoints(self, client, auth):
        bh, _ = _beneficiary_of(client, auth)
        assert client.get("/vault/messages", headers=bh).status_code == 401
        assert client.get("/auth/me", headers=bh).status_code == 401
        assert client.get("/vault/status", headers=bh).status_code == 401
        assert client.post("/vault/trigger", json=TRIGGER_BODY, headers=bh).status_code in (401, 422)

    def test_owner_cannot_call_beneficiary_endpoints(self, client, auth):
        assert client.get("/access/status", headers=auth).status_code == 401
        assert client.get("/access/messages", headers=auth).status_code == 401


class TestDatabaseZeroKnowledge:
    def test_db_holds_no_plaintext_secrets(self, client, auth):
        """After a full lifecycle, no secret plaintext exists in any table."""
        from sqlalchemy import inspect as sa_inspect

        from db import SessionLocal, engine
        from models import AuditEvent

        sentinel_pw = f"ZK-{uuid.uuid4().hex}@example.com"
        # Use a distinctive login password and invitation flow, then scan.
        email = f"zk-{uuid.uuid4().hex[:8]}@example.com"
        password = f"ZkSecret-{uuid.uuid4().hex}!"
        from models import User, Vault
        from services.auth import hash_password

        from datetime import UTC, datetime

        db = SessionLocal()
        try:
            user = User(
                email=email,
                password_hash=hash_password(password),
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            vault = Vault(user_id=user.id, name="Primary Vault", is_primary=True)
            db.add(vault)
            db.commit()
        finally:
            db.close()
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        # Login is cookie-only; mint an explicit token like conftest does.
        from services.auth import create_access_token

        db = SessionLocal()
        try:
            u = db.query(User).filter(User.email == email).first()
            v = db.query(Vault).filter(Vault.user_id == u.id).first()
            owner_h = {"Authorization": f"Bearer {create_access_token(u.id, v.id, role='owner')}"}
        finally:
            db.close()
        client.post(
            "/vault/messages",
            json={"label": "zk", "ciphertext": _CT, "wrapped_mek": _WMEK},
            headers=owner_h,
        )
        bh, raw_invite = _beneficiary_of(client, owner_h)
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=owner_h)
        client.get("/access/messages", headers=bh)
        client.request(
            "DELETE", "/vault/messages",
            json={"password": password, "confirm": True}, headers=owner_h,
        )

        secrets = [password, raw_invite, sentinel_pw]
        db = SessionLocal()
        try:
            insp = sa_inspect(engine)
            hits = []
            for table in insp.get_table_names():
                if table == "alembic_version":
                    continue
                cols = [c["name"] for c in insp.get_columns(table)]
                rows = db.execute(
                    __import__("sqlalchemy").text(f"SELECT * FROM {table}")
                ).mappings().all()
                for row in rows:
                    for c in cols:
                        val = row.get(c)
                        if isinstance(val, str):
                            for s in secrets:
                                if s and s in val:
                                    hits.append((table, c))
            assert hits == [], f"plaintext secrets found in DB: {hits}"
            # Hashes, not plaintext: password verifier is Argon2id, invite is SHA-256.
            u = db.query(User).filter(User.email == email).first()
            assert u.password_hash.startswith("$argon2")
            for row in db.query(AuditEvent).all():
                assert password not in (row.event_metadata or "")
        finally:
            db.close()
