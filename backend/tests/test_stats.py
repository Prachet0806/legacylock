"""Tests for /stats and /health endpoints."""

import base64

_WMEK = base64.b64encode(b"0" * 32).decode()
WIPE_BODY = {"password": "TestPass123!Long", "confirm": True}
TRIGGER_BODY = {"password": "TestPass123!Long", "confirm": True}
RESET_BODY = {"password": "TestPass123!Long", "confirm": True}


class TestHealth:
    def test_health_no_auth(self, client):
        """Health endpoint is public — no API key required."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_readyz(self, client):
        res = client.get("/readyz")
        assert res.status_code in (200, 500)


class TestStats:
    def test_stats_requires_auth(self, client):
        assert client.get("/stats").status_code == 401

    def test_stats_shape(self, client, auth):
        res = client.get("/stats", headers=auth)
        assert res.status_code == 200
        data = res.json()
        for field in (
            "message_count",
            "beneficiary_count",
            "last_check_in",
            "heartbeat_interval",
            "heartbeat_grace",
            "vault_status",
        ):
            assert field in data, f"Missing field: {field}"

    def test_message_count_reflects_vault(self, client, auth):
        # Wipe first
        client.request("DELETE", "/vault/messages", json=WIPE_BODY, headers=auth)
        initial = client.get("/stats", headers=auth).json()["message_count"]
        client.post(
            "/vault/messages",
            json={
                "label": "test",
                "ciphertext": base64.b64encode(b"x" * 16).decode(),
                "wrapped_mek": _WMEK,
            },
            headers=auth,
        )
        after = client.get("/stats", headers=auth).json()["message_count"]
        assert after == initial + 1
        client.request("DELETE", "/vault/messages", json=WIPE_BODY, headers=auth)

    def test_beneficiary_count_reflects_adds(self, client, auth):
        initial = client.get("/stats", headers=auth).json()["beneficiary_count"]
        res = client.post("/beneficiaries", json={"name": "X", "email": "x@x.com"}, headers=auth)
        ben_id = res.json()["id"]
        after = client.get("/stats", headers=auth).json()["beneficiary_count"]
        assert after == initial + 1
        client.delete(f"/beneficiaries/{ben_id}", headers=auth)

    def test_vault_status_in_stats(self, client, auth):
        client.post("/vault/reset-status", json=RESET_BODY, headers=auth)
        data = client.get("/stats", headers=auth).json()
        assert data["vault_status"] == "active"

    def test_vault_status_reflects_trigger(self, client, auth):
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        data = client.get("/stats", headers=auth).json()
        assert data["vault_status"] == "triggered"
        client.post("/vault/reset-status", json=RESET_BODY, headers=auth)
