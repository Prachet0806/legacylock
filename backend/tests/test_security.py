"""Tests for P1 hardening: metadata caps, origin check, login timing safety, logout scope."""

import base64

_WMEK = base64.b64encode(b"0" * 32).decode()
_CT = base64.b64encode(b"x" * 16).decode()


def _msg(label="t", **kw):
    body = {"label": label, "ciphertext": _CT, "wrapped_mek": _WMEK}
    body.update(kw)
    return body


class TestMetadataCaps:
    def test_huge_metadata_rejected(self, client, auth):
        big = {f"k{i}": "x" * 500 for i in range(30)}
        r = client.post("/vault/messages", json=_msg(crypto_metadata=big), headers=auth)
        assert r.status_code == 422

    def test_deep_metadata_rejected(self, client, auth):
        deep: dict = {}
        cur = deep
        for i in range(6):
            cur["n"] = {}
            cur = cur["n"]
        r = client.post("/vault/messages", json=_msg(crypto_metadata=deep), headers=auth)
        assert r.status_code == 422

    def test_small_metadata_accepted(self, client, auth):
        r = client.post("/vault/messages", json=_msg(crypto_metadata={"iv": "eA=="}), headers=auth)
        assert r.status_code == 201

    def test_kdf_contract_exact_and_capped(self, client, auth):
        import base64

        good = {
            "wrapped_vmk": _WMEK,
            "vmk_crypto_version": 1,
            "vmk_kdf_algorithm": "PBKDF2-SHA256",
            "vmk_kdf_salt": base64.b64encode(b"s" * 16).decode(),
            "vmk_kdf_parameters": {"iterations": 600000},
        }
        assert client.put("/vault/crypto-material", json=good, headers=auth).status_code == 200
        weak = dict(good, vmk_kdf_parameters={"iterations": 100000})
        assert client.put("/vault/crypto-material", json=weak, headers=auth).status_code == 422
        wrong_algo = dict(good, vmk_kdf_algorithm="argon2id")
        assert (
            client.put("/vault/crypto-material", json=wrong_algo, headers=auth).status_code == 422
        )
        body = {
            "wrapped_vmk": _WMEK,
            "vmk_crypto_version": 1,
            "vmk_kdf_algorithm": "PBKDF2-SHA256",
            "vmk_kdf_salt": base64.b64encode(b"s" * 16).decode(),
            "vmk_kdf_parameters": {"iterations": 600000, **{f"x{i}": "y" * 300 for i in range(20)}},
        }
        assert client.put("/vault/crypto-material", json=body, headers=auth).status_code == 422


class TestOriginCheck:
    def test_evil_origin_blocked(self, client, auth):
        r = client.post(
            "/vault/messages",
            json=_msg(),
            headers={**auth, "Origin": "http://evil.example.com"},
        )
        assert r.status_code == 403

    def test_allowed_origin_passes(self, client, auth):
        r = client.post(
            "/vault/messages",
            json=_msg(),
            headers={**auth, "Origin": "http://localhost:3000"},
        )
        assert r.status_code == 201

    def test_no_origin_passes(self, client, auth):
        # API clients (curl/services) send no Origin and must keep working.
        r = client.post("/vault/messages", json=_msg(), headers=auth)
        assert r.status_code == 201

    def test_get_unaffected_by_origin(self, client):
        r = client.get("/health", headers={"Origin": "http://evil.example.com"})
        assert r.status_code == 200


class TestLoginLogoutScope:
    def test_unknown_user_401(self, client):
        r = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "TestPass123!Long"},
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid email or password"

    def test_logout_without_cookie_revokes_nothing(self, client, auth):
        # Bearer-only logout must NOT mass-revoke: session stays valid.
        r = client.post("/auth/logout", headers=auth)
        assert r.status_code == 200
        assert client.get("/auth/me", headers=auth).status_code == 200


class TestAuditAtomicity:
    def test_failed_mutation_leaves_no_audit_row(self, client, auth):
        """A rejected request must not leave an orphan audit event behind."""
        from db import SessionLocal
        from models import AuditEvent

        def count():
            db = SessionLocal()
            try:
                return db.query(AuditEvent).count()
            finally:
                db.close()

        before = count()
        # 422 validation failure: nothing may be persisted
        r = client.post(
            "/vault/messages",
            json={
                "label": "t",
                "ciphertext": "!!!not-base64",
                "wrapped_mek": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            },
            headers=auth,
        )
        assert r.status_code == 422
        assert count() == before
