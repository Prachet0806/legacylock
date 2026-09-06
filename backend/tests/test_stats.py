"""Tests for /stats and /health endpoints."""



class TestHealth:
    def test_health_no_auth(self, client):
        """Health endpoint is public — no API key required."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


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
        client.delete("/vault/messages", headers=auth)
        initial = client.get("/stats", headers=auth).json()["message_count"]
        client.post("/vault/messages", json={"label": "test", "encrypted_content": "abc"}, headers=auth)
        after = client.get("/stats", headers=auth).json()["message_count"]
        assert after == initial + 1
        client.delete("/vault/messages", headers=auth)

    def test_beneficiary_count_reflects_adds(self, client, auth):
        initial = client.get("/stats", headers=auth).json()["beneficiary_count"]
        res = client.post("/beneficiaries", json={"name": "X", "email": "x@x.com"}, headers=auth)
        ben_id = res.json()["id"]
        after = client.get("/stats", headers=auth).json()["beneficiary_count"]
        assert after == initial + 1
        client.delete(f"/beneficiaries/{ben_id}", headers=auth)

    def test_vault_status_in_stats(self, client, auth):
        client.post("/vault/reset-status", headers=auth)
        data = client.get("/stats", headers=auth).json()
        assert data["vault_status"] == "active"

    def test_vault_status_reflects_trigger(self, client, auth):
        client.post("/vault/trigger", headers=auth)
        data = client.get("/stats", headers=auth).json()
        assert data["vault_status"] == "triggered"
        client.post("/vault/reset-status", headers=auth)
