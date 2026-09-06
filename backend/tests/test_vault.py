"""Tests for /vault/messages routes."""

import base64

import pytest

_WMEK = base64.b64encode(b"0" * 32).decode()
_IV = base64.b64encode(b"1" * 12).decode()

MESSAGE_A = {"label": "Bank Info", "ciphertext": "ZW5jcnlwdGVkY29udGVudA==", "wrapped_mek": _WMEK, "iv": _IV}
MESSAGE_B = {"label": "Seed Phrase", "ciphertext": "c2VlZHBocmFzZWVuY3J5cHRlZA==", "wrapped_mek": _WMEK, "iv": _IV}

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
        assert data["encrypted_content"] == MESSAGE_A["encrypted_content"]
        assert data["label"] == MESSAGE_A["label"]

    def test_get_not_found(self, client, auth):
        res = client.get("/vault/messages/99999", headers=auth)
        assert res.status_code == 404

    def test_update_message(self, client, auth):
        post = client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        msg_id = post.json()["id"]
        updated = {"label": "Updated Label", "encrypted_content": "bmV3Y2lwaGVydGV4dA=="}
        res = client.put(f"/vault/messages/{msg_id}", json=updated, headers=auth)
        assert res.status_code == 200
        # Verify the update was persisted
        get = client.get(f"/vault/messages/{msg_id}", headers=auth)
        assert get.json()["label"] == "Updated Label"
        assert get.json()["encrypted_content"] == updated["encrypted_content"]

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
        res = client.request("DELETE", "/vault/messages", json={"password": "wrong-password-123", "confirm": True}, headers=auth)
        assert res.status_code == 401

    def test_wipe_requires_confirm(self, client, auth):
        res = client.request("DELETE", "/vault/messages", json={"password": "TestPass123!Long"}, headers=auth)
        assert res.status_code == 422

    def test_list_returns_meta_not_content(self, client, auth):
        """GET /vault/messages must NOT return encrypted_content in the list."""
        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        msgs = client.get("/vault/messages", headers=auth).json()
        assert "encrypted_content" not in msgs[0]
        assert "id" in msgs[0]
        assert "label" in msgs[0]
        assert "created_at" in msgs[0]

    def test_list_ordered_descending(self, client, auth):
        """Messages should be returned newest-first."""
        import time
        client.post("/vault/messages", json=MESSAGE_A, headers=auth)
        time.sleep(0.05)  # ensure different timestamps in SQLite
        client.post("/vault/messages", json=MESSAGE_B, headers=auth)
        msgs = client.get("/vault/messages", headers=auth).json()
        assert msgs[0]["label"] == MESSAGE_B["label"]


class TestVaultValidation:
    def test_label_required(self, client, auth):
        res = client.post("/vault/messages", json={"ciphertext": "YWJj", "wrapped_mek": _WMEK}, headers=auth)
        assert res.status_code == 422

    def test_content_required(self, client, auth):
        res = client.post("/vault/messages", json={"label": "test"}, headers=auth)
        assert res.status_code == 422

    def test_wrapped_mek_required(self, client, auth):
        res = client.post("/vault/messages", json={"label": "t", "ciphertext": "YWJj"}, headers=auth)
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
        res = client.post("/vault/messages", json={"label": "", "ciphertext": "YWJj", "wrapped_mek": _WMEK}, headers=auth)
        assert res.status_code == 422
