"""Tests for /vault/messages routes."""

import base64

import pytest

_WMEK = base64.b64encode(b"0" * 32).decode()
_IV = base64.b64encode(b"1" * 12).decode()

MESSAGE_A = {
    "label": "Bank Info",
    "ciphertext": "ZW5jcnlwdGVkY29udGVudA==",
    "wrapped_mek": _WMEK,
    "crypto_metadata": {"iv": _IV},
}
MESSAGE_B = {
    "label": "Seed Phrase",
    "ciphertext": "c2VlZHBocmFzZWVuY3J5cHRlZA==",
    "wrapped_mek": _WMEK,
    "crypto_metadata": {"iv": _IV},
}

WIPE_BODY = {"password": "TestPass123!Long", "confirm": True}


@pytest.fixture(autouse=True)
def wipe_between_tests(client, auth):
    """Wipe vault before each test for a clean state."""
    yield
    client.request("DELETE", "/vault/messages", json=WIPE_BODY, headers=auth)


class TestVaultAuth:
    def test_save_requires_auth(self, client):
        res = client.post("/vault/messages", json=MESSAGE_A)
        assert res.status_code == 401

    def test_list_requires_auth(self, client):
        res = client.get("/vault/messages")
        assert res.status_code == 401

    def test_get_requires_auth(self, client):
        res = client.get("/vault/messages/1")
        assert res.status_code == 401

    def test_delete_requires_auth(self, client):
        res = client.delete("/vault/messages/1")
        assert res.status_code == 401

    def test_wipe_requires_auth(self, client):
        res = client.request("DELETE", "/vault/messages", json=WIPE_BODY)
        assert res.status_code == 401


class TestVaultCRUD:
    def test_list_empty(self, client, auth):
        res = client.get("/vault/messages", headers=auth)
        assert res.status_code == 200
        assert res.json() == []

    def test_save_message(self, client, auth):
        res = client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        assert res.status_code == 201
        data = res.json()
        assert "id" in data
        assert data["id"] > 0

    def test_list_after_save(self, client, auth):
        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        res = client.get("/vault/messages", headers=auth)
        assert res.status_code == 200
        msgs = res.json()
        assert len(msgs) == 1
        assert msgs[0]["label"] == MESSAGE_A["label"]

    def test_get_by_id(self, client, auth):
        post = client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        msg_id = post.json()["id"]
        res = client.get(f"/vault/messages/{msg_id}", headers=auth)
        assert res.status_code == 200
        data = res.json()
        assert data["ciphertext"] == MESSAGE_A["ciphertext"]
        assert data["label"] == MESSAGE_A["label"]
        # Canonical shape: no legacy top-level fields; IV inside metadata.
        assert "encrypted_content" not in data
        assert "iv" not in data
        assert data["crypto_metadata"]["iv"] == _IV

    def test_legacy_compat_fields_ignored(self, client, auth):
        """Removed fields (encrypted_content, top-level iv) are ignored, not stored."""
        body = dict(MESSAGE_A, encrypted_content="Zm9v", iv=_IV)
        post = client.post("/vault/messages", json=body, headers=auth)
        assert post.status_code == 201
        data = client.get(f"/vault/messages/{post.json()['id']}", headers=auth).json()
        assert "encrypted_content" not in data
        assert "iv" not in data
        assert data["ciphertext"] == MESSAGE_A["ciphertext"]

    def test_get_not_found(self, client, auth):
        res = client.get("/vault/messages/99999", headers=auth)
        assert res.status_code == 404

    def test_update_message(self, client, auth):
        post = client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        msg_id = post.json()["id"]
        updated = {"label": "Updated Label", "ciphertext": "bmV3Y2lwaGVydGV4dA=="}
        res = client.put(f"/vault/messages/{msg_id}", json=updated, headers=auth)
        assert res.status_code == 200
        # Verify the update was persisted
        get = client.get(f"/vault/messages/{msg_id}", headers=auth)
        assert get.json()["label"] == "Updated Label"
        assert get.json()["ciphertext"] == updated["ciphertext"]

    def test_update_not_found(self, client, auth):
        res = client.put("/vault/messages/99999", json=MESSAGE_A, headers=auth)
        assert res.status_code == 404

    def test_delete_message(self, client, auth):
        post = client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        msg_id = post.json()["id"]
        res = client.delete(f"/vault/messages/{msg_id}", headers=auth)
        assert res.status_code == 204
        # Confirm it's gone
        get = client.get(f"/vault/messages/{msg_id}", headers=auth)
        assert get.status_code == 404

    def test_delete_not_found(self, client, auth):
        res = client.delete("/vault/messages/99999", headers=auth)
        assert res.status_code == 404

    def test_wipe_vault(self, client, auth):
        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        client.post("/vault/messages", json=MESSAGE_B, headers=auth)
        res = client.request("DELETE", "/vault/messages", json=WIPE_BODY, headers=auth)
        assert res.status_code == 204
        list_res = client.get("/vault/messages", headers=auth)
        assert list_res.json() == []

    def test_wipe_requires_password(self, client, auth):
        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        res = client.request(
            "DELETE",
            "/vault/messages",
            json={"password": "wrong-password-123", "confirm": True},
            headers=auth,
        )
        assert res.status_code == 401

    def test_wipe_requires_confirm(self, client, auth):
        res = client.request(
            "DELETE", "/vault/messages", json={"password": "TestPass123!Long"}, headers=auth
        )
        assert res.status_code == 422

    def test_list_returns_meta_not_content(self, client, auth):
        """GET /vault/messages must NOT return encrypted_content in the list."""
        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        msgs = client.get("/vault/messages", headers=auth).json()
        assert "encrypted_content" not in msgs[0]
        assert "id" in msgs[0]
        assert "label" in msgs[0]
        assert "created_at" in msgs[0]

    def test_message_category_contract(self, client):
        """Backend enum is the contract the frontend mirrors (11 values)."""
        from models import MessageCategory

        assert sorted(c.value for c in MessageCategory) == sorted(
            [
                "financial",
                "insurance",
                "digital_assets",
                "digital_identity",
                "digital_storage",
                "devices",
                "online_accounts",
                "property",
                "dependents",
                "business",
                "personal",
            ]
        )

    def test_list_ordered_descending(self, client, auth):
        """Messages should be returned newest-first."""
        import time

        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        time.sleep(0.05)  # ensure different timestamps in SQLite
        client.post("/vault/messages", json=MESSAGE_B, headers=auth)
        msgs = client.get("/vault/messages", headers=auth).json()
        assert msgs[0]["label"] == MESSAGE_B["label"]

    def test_login_provisions_no_vault_but_setup_does(self, client):
        """Login provisions nothing; PUT /vault/crypto-material creates primary."""
        import base64
        import uuid

        from db import SessionLocal
        from models import User, Vault
        from services.auth import create_access_token, hash_password

        email = f"fresh-{uuid.uuid4().hex[:8]}@example.com"
        db = SessionLocal()
        try:
            from datetime import UTC, datetime

            user = User(
                email=email,
                password_hash=hash_password("TestPass123!Long"),
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            uid = user.id
        finally:
            db.close()
        r = client.post("/auth/login", json={"email": email, "password": "TestPass123!Long"})
        assert r.status_code == 200
        assert "access_token" not in r.json()
        db = SessionLocal()
        try:
            assert db.query(Vault).filter(Vault.user_id == uid).count() == 0, (
                "login must not provision vaults"
            )
        finally:
            db.close()
        # Explicit setup provisions the primary vault
        token = create_access_token(uid, None, role="owner")
        body = {
            "wrapped_vmk": base64.b64encode(b"0" * 32).decode(),
            "vmk_crypto_version": 1,
            "vmk_kdf_algorithm": "PBKDF2-SHA256",
            "vmk_kdf_salt": base64.b64encode(b"s" * 16).decode(),
            "vmk_kdf_parameters": {"iterations": 600000},
        }
        assert (
            client.put(
                "/vault/crypto-material",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            == 200
        )
        db = SessionLocal()
        try:
            vaults = db.query(Vault).filter(Vault.user_id == uid).all()
            assert len(vaults) == 1 and vaults[0].is_primary is True
        finally:
            db.close()


class TestVaultValidation:
    def test_label_required(self, client, auth):
        res = client.post(
            "/vault/messages", json={"ciphertext": "YWJj", "wrapped_mek": _WMEK}, headers=auth
        )
        assert res.status_code == 422

    def test_content_required(self, client, auth):
        res = client.post("/vault/messages", json={"label": "test"}, headers=auth)
        assert res.status_code == 422

    def test_wrapped_mek_required(self, client, auth):
        res = client.post(
            "/vault/messages", json={"label": "t", "ciphertext": "YWJj"}, headers=auth
        )
        assert res.status_code == 422

    def test_bad_base64_rejected(self, client, auth):
        res = client.post(
            "/vault/messages",
            json={"label": "t", "ciphertext": "!!!not-base64", "wrapped_mek": _WMEK},
            headers=auth,
        )
        assert res.status_code == 422

    def test_label_too_long(self, client, auth):
        payload = {"label": "x" * 201, "ciphertext": "YWJj", "wrapped_mek": _WMEK}
        res = client.post("/vault/messages", json=payload, headers=auth)
        assert res.status_code == 422

    def test_empty_label(self, client, auth):
        res = client.post(
            "/vault/messages",
            json={"label": "", "ciphertext": "YWJj", "wrapped_mek": _WMEK},
            headers=auth,
        )
        assert res.status_code == 422
