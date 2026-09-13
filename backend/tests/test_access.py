"""Tests for invite accept, access gating, share submit, share-assignments."""

TRIGGER_BODY = {"password": "TestPass123!Long", "confirm": True}
RESET_BODY = {"password": "TestPass123!Long", "confirm": True}


def _invite_link(client, auth):
    post = client.post("/beneficiaries", json={"name": "Ben", "email": "ben@test.com"}, headers=auth)
    assert post.status_code == 201
    ben_id = post.json()["id"]
    r = client.post(f"/beneficiaries/{ben_id}/invite", headers=auth)
    assert r.status_code == 200
    link = r.json()["invitation_link"]
    return link.rsplit("/", 1)[-1]


def _beneficiary_headers(client, auth):
    """Accept an invite and return explicit beneficiary auth headers.

    Builds the JWT directly (like the owner fixture) for hermetic tests and
    clears the shared client's cookie jar so no session leaks across tests.
    """
    from db import SessionLocal
    from models import Beneficiary
    from services.auth import BENEFICIARY_TOKEN_EXPIRE_MINUTES, create_access_token

    client.cookies.clear()
    raw = _invite_link(client, auth)
    r = client.post(f"/access/invite/{raw}/accept")
    assert r.status_code == 200
    assert "access_token" not in r.json()
    ben_id = r.json()["beneficiary_id"]
    db = SessionLocal()
    try:
        b = db.query(Beneficiary).filter(Beneficiary.id == ben_id).first()
        assert b is not None
        vault_id = b.vault_id
    finally:
        db.close()
    token = create_access_token(
        ben_id, vault_id, role="beneficiary",
        expires_minutes=BENEFICIARY_TOKEN_EXPIRE_MINUTES,
    )
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


class TestInviteFlow:
    def test_invite_stores_hash_not_raw(self, client, auth):
        from db import SessionLocal
        from models import Beneficiary
        raw = _invite_link(client, auth)
        db = SessionLocal()
        try:
            rows = db.query(Beneficiary).all()
            assert rows
            for b in rows:
                assert b.invitation_hash != raw
                assert len(b.invitation_hash) == 64  # sha256 hex
        finally:
            db.close()

    def test_accept_and_replay(self, client, auth):
        client.cookies.clear()
        raw = _invite_link(client, auth)
        assert client.get(f"/access/invite/{raw}/status").status_code == 200
        r = client.post(f"/access/invite/{raw}/accept")
        assert r.status_code == 200
        assert "access_token" not in r.json()
        # HttpOnly session + refresh cookies set, nothing in the body
        assert "legacylock_beneficiary_session" in client.cookies
        assert "legacylock_beneficiary_refresh" in client.cookies
        # rotated: replay same link is now invalid
        r2 = client.post(f"/access/invite/{raw}/accept")
        assert r2.status_code in (404, 409)
        client.cookies.clear()

    def test_session_refresh_flow(self, client, auth):
        client.cookies.clear()
        raw = _invite_link(client, auth)
        client.post(f"/access/invite/{raw}/accept")
        old_refresh = client.cookies.get("legacylock_beneficiary_refresh")
        assert old_refresh
        # No JWT needed: the refresh cookie alone renews the session
        r = client.post("/access/session")
        assert r.status_code == 200
        assert "access_token" not in r.json()
        assert client.cookies.get("legacylock_beneficiary_refresh") != old_refresh
        # Single-use: the old refresh credential is dead
        client.cookies.clear()
        client.cookies.set("legacylock_beneficiary_refresh", old_refresh, path="/access")
        r2 = client.post("/access/session")
        assert r2.status_code == 401
        # No credential at all
        assert client.post("/access/session").status_code == 401
        client.cookies.clear()

    def test_status_gated_by_trigger(self, client, auth):
        bh = _beneficiary_headers(client, auth)
        assert client.get("/access/status", headers=bh).status_code == 403
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            r = client.get("/access/status", headers=bh)
            assert r.status_code == 200
            assert r.json()["vault_status"] == "triggered"
        finally:
            client.post("/vault/reset-status", json=RESET_BODY, headers=auth)


class TestShareRemoved:
    def test_share_endpoint_gone(self, client, auth):
        # Server-side share tracking was removed: the server cannot verify
        # shares it must never see. Old clients get an explicit 410.
        bh = _beneficiary_headers(client, auth)
        r = client.post("/access/share", json={"share_hash": "a" * 64}, headers=bh)
        assert r.status_code == 410
        assert client.post("/access/share/report-mismatch", headers=bh).status_code in (404, 405)

    def test_recovery_rate_limited(self, client, auth, monkeypatch):
        # Abuse protection now lives in strict per-route buckets.
        monkeypatch.setenv("RATE_LIMIT_TESTING", "1")
        bh = _beneficiary_headers(client, auth)
        statuses = {
            client.post("/access/session", headers=bh).status_code for _ in range(15)
        }
        assert 429 in statuses


class TestShareAssignments:
    def test_metadata_only_both_prefixes(self, client, auth):
        for path in ("/vault/share-assignments", "/access/share-assignments"):
            r = client.get(path, headers=auth)
            assert r.status_code == 200
            for row in r.json():
                assert "share" not in str(list(row.keys())).lower() or "share_index" in row
                assert "ciphertext" not in row
                assert "wrapped" not in str(list(row.keys())).lower()


class TestRecoveryMessages:
    def _setup(self, client, auth):
        import base64
        wmek = base64.b64encode(b"0" * 32).decode()
        ct = base64.b64encode(b"x" * 16).decode()
        mid = client.post(
            "/vault/messages",
            json={"label": "will", "ciphertext": ct, "wrapped_mek": wmek},
            headers=auth,
        ).json()["id"]
        return mid, _beneficiary_headers(client, auth)

    def test_gated_before_trigger(self, client, auth):
        _, bh = self._setup(client, auth)
        assert client.get("/access/messages", headers=bh).status_code == 403
        assert client.get("/access/messages/1", headers=bh).status_code == 403

    def test_list_and_get_after_trigger(self, client, auth):
        mid, bh = self._setup(client, auth)
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            rows = client.get("/access/messages", headers=bh).json()
            assert len(rows) == 1
            assert rows[0]["label"] == "will"
            assert "ciphertext" not in rows[0]
            detail = client.get(f"/access/messages/{mid}", headers=bh).json()
            assert detail["ciphertext"]
            assert detail["wrapped_mek"]
            assert "plaintext" not in str(detail.keys()).lower()
            assert client.get("/access/messages/99999", headers=bh).status_code == 404
        finally:
            client.post("/vault/reset-status", json=RESET_BODY, headers=auth)

class TestAuditPersisted:
    def test_trigger_writes_audit_row(self, client, auth):
        from db import SessionLocal
        from models import AuditEvent
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            db = SessionLocal()
            try:
                rows = db.query(AuditEvent).filter(AuditEvent.event_type == "vault.trigger").all()
                assert len(rows) >= 1
            finally:
                db.close()
        finally:
            client.post("/vault/reset-status", json=RESET_BODY, headers=auth)
