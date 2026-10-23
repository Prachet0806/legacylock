"""Phase B regression: jti revocation, notification durability, audit correlation."""


def _owner_setup(client, auth):
    import base64

    base = {
        "wrapped_vmk": base64.b64encode(b"0" * 40).decode(),
        "expected_revision": 1,
        "vmk_crypto_version": 1,
        "vmk_kdf_algorithm": "PBKDF2-SHA256",
        "vmk_kdf_salt": base64.b64encode(b"1" * 16).decode(),
        "vmk_kdf_parameters": {"iterations": 600000},
    }
    assert client.put("/vault/crypto-material", json=base, headers=auth).status_code == 200


class TestBeneficiarySessionBinding:
    def _invite_accept(self, client, auth):
        import uuid

        _owner_setup(client, auth)
        email = f"ben-{uuid.uuid4().hex[:8]}@example.com"
        post = client.post("/beneficiaries", json={"name": "Ben", "email": email}, headers=auth)
        assert post.status_code == 201
        ben_id = post.json()["id"]
        inv = client.post(f"/beneficiaries/{ben_id}/invite", headers=auth)
        assert inv.status_code == 200
        link = inv.json()["invitation_link"]
        raw = link.split("token=", 1)[-1]
        acc = client.post("/access/invitation/accept", json={"token": raw})
        assert acc.status_code == 200
        # Cookies carry the session; extract for direct use.
        access = acc.cookies.get("legacylock_beneficiary_session")
        refresh = acc.cookies.get("legacylock_beneficiary_refresh")
        assert access and refresh
        return ben_id, {"access": access, "refresh": refresh}

    def test_revoke_kills_session_token(self, client, auth):
        ben_id, toks = self._invite_accept(client, auth)
        from db import SessionLocal
        from models import Beneficiary

        db = SessionLocal()
        try:
            ben = db.query(Beneficiary).filter(Beneficiary.id == ben_id).first()
            assert ben.session_jti is not None
        finally:
            db.close()
        # Revoke with the live token → old access JWT must 401 afterwards.
        rev = client.post(
            "/access/revoke", cookies={"legacylock_beneficiary_session": toks["access"]}
        )
        assert rev.status_code == 200
        again = client.post(
            "/access/revoke", cookies={"legacylock_beneficiary_session": toks["access"]}
        )
        assert again.status_code == 401

    def test_refresh_rotation_invalidates_old(self, client, auth):
        _, toks = self._invite_accept(client, auth)
        first = client.post(
            "/access/session",
            cookies={"legacylock_beneficiary_refresh": toks["refresh"]},
        )
        assert first.status_code == 200
        # Old refresh credential is single-use.
        replay = client.post(
            "/access/session",
            cookies={"legacylock_beneficiary_refresh": toks["refresh"]},
        )
        assert replay.status_code == 409


class TestAuditCorrelation:
    def test_record_audit_attaches_request_context(self, client, auth):
        from db import SessionLocal
        from models import AuditEvent
        from services.audit import record_audit
        from services.request_ctx import client_ip_ctx, request_id_ctx

        request_id_ctx.set("corr1234abcd")
        client_ip_ctx.set("10.0.0.7")
        db = SessionLocal()
        try:
            record_audit(db, None, "owner", 1, "test.correlation", {})
            db.commit()
            row = (
                db.query(AuditEvent)
                .filter(AuditEvent.event_type == "test.correlation")
                .order_by(AuditEvent.id.desc())
                .first()
            )
            assert row.request_id == "corr1234abcd"
            assert row.ip_address == "10.0.0.7"
        finally:
            request_id_ctx.set(None)
            client_ip_ctx.set(None)
            db.close()
