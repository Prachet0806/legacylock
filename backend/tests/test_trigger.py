"""Tests for /vault/status, /vault/trigger, /vault/reset-status routes."""

import pytest

TRIGGER_BODY = {"password": "TestPass123!Long", "confirm": True}
RESET_BODY = {"password": "TestPass123!Long", "confirm": True}


@pytest.fixture(autouse=True)
def reset_vault_status(client, auth):
    """Always reset vault status to 'active' after each test."""
    yield
    client.post("/vault/reset-status", json=RESET_BODY, headers=auth)


class TestTriggerAuth:
    def test_status_requires_auth(self, client):
        assert client.get("/vault/status").status_code == 401

    def test_trigger_requires_auth(self, client):
        assert client.post("/vault/trigger", json=TRIGGER_BODY).status_code == 401

    def test_reset_requires_auth(self, client):
        assert client.post("/vault/reset-status", json=RESET_BODY).status_code == 401


class TestVaultStatus:
    def test_get_default_status(self, client, auth):
        res = client.get("/vault/status", headers=auth)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "active"
        assert data["triggered_at"] is None
        assert data["grace_started_at"] is None

    def test_status_fields_present(self, client, auth):
        data = client.get("/vault/status", headers=auth).json()
        for field in ("status", "triggered_at", "grace_started_at", "share_threshold", "share_total"):
            assert field in data


class TestVaultTrigger:
    def test_trigger_vault(self, client, auth):
        res = client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        assert res.status_code == 200
        data = res.json()
        assert "triggered_at" in data
        assert data["triggered_at"] is not None

    def test_trigger_sets_status(self, client, auth):
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        status = client.get("/vault/status", headers=auth).json()
        assert status["status"] == "triggered"
        assert status["triggered_at"] is not None

    def test_trigger_timestamp_valid_iso(self, client, auth):
        from datetime import datetime
        res = client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth).json()
        # Should parse without exception
        datetime.fromisoformat(res["triggered_at"].replace("Z", "+00:00"))

    def test_trigger_idempotent_returns_200(self, client, auth):
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        second = client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        assert second.status_code == 200
        assert second.json().get("already") is True

    def test_trigger_requires_confirm(self, client, auth):
        res = client.post("/vault/trigger", json={"password": "TestPass123!Long"}, headers=auth)
        assert res.status_code == 422

    def test_trigger_wrong_password(self, client, auth):
        res = client.post("/vault/trigger", json={"password": "wrong-password-123", "confirm": True}, headers=auth)
        assert res.status_code == 401


class TestVaultReset:
    def test_reset_returns_active(self, client, auth):
        client.post("/vault/trigger", json=TRIGGER_BODY, headers=auth)
        res = client.post("/vault/reset-status", json=RESET_BODY, headers=auth)
        assert res.status_code == 200
        status = client.get("/vault/status", headers=auth).json()
        assert status["status"] == "active"
        assert status["triggered_at"] is None
        assert status["grace_started_at"] is None

    def test_reset_requires_confirm(self, client, auth):
        res = client.post("/vault/reset-status", json={"password": "TestPass123!Long"}, headers=auth)
        assert res.status_code == 422
