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
        raw = _invite_link(client, auth)
        assert client.get(f"/access/invite/{raw}/status").status_code == 200
        r = client.post(f"/access/invite/{raw}/accept")
        assert r.status_code == 200
        assert "access_token" in r.json()
        # rotated: replay same link is now invalid
        r2 = client.post(f"/access/invite/{raw}/accept")
        assert r2.status_code in (404, 409)

    def test_status_gated_by_trigger(self, client, auth):
        raw = _invite_link(client, auth)
        token = client.post(f"/access/invite/{raw}/accept").json()["access_token"]
        bh = {"Authorization": f"Bearer {token}"}
        assert client.get("/access/status", headers=bh).status_code == 403
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            r = client.get("/access/status", headers=bh)
            assert r.status_code == 200
            assert r.json()["vault_status"] == "triggered"
        finally:
            client.post("/vault/reset-status", json=RESET_BODY, headers=auth)


class TestShareSubmit:
    def test_submit_idempotent_and_gated(self, client, auth):
        import base64
        raw = _invite_link(client, auth)
        token = client.post(f"/access/invite/{raw}/accept").json()["access_token"]
        bh = {"Authorization": f"Bearer {token}"}
        share = base64.b64encode(b"s" * 48).decode()
        # gated before trigger
        assert client.post("/access/share", json={"share": share}, headers=bh).status_code == 403
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            r1 = client.post("/access/share", json={"share": share}, headers=bh)
            assert r1.status_code == 200
            r2 = client.post("/access/share", json={"share": share}, headers=bh)
            assert r2.status_code == 200
            assert r2.json().get("duplicate") is True
        finally:
            client.post("/vault/reset-status", json=RESET_BODY, headers=auth)


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
        raw = _invite_link(client, auth)
        token = client.post(f"/access/invite/{raw}/accept").json()["access_token"]
        return mid, {"Authorization": f"Bearer {token}"}

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

    def test_mismatch_locks_out(self, client, auth):
        _, bh = self._setup(client, auth)
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        try:
            for _ in range(5):
                assert client.post("/access/share/report-mismatch", headers=bh).status_code == 200
            # locked: next submit of a *new* share is rejected
            import base64
            new_share = base64.b64encode(b"n" * 48).decode()
            assert client.post("/access/share", json={"share": new_share}, headers=bh).status_code == 429
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
