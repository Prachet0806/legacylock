"""Tests for /vault/status, /vault/trigger, /vault/reset-status routes."""

import pytest


@pytest.fixture(autouse=True)
def reset_vault_status(client, auth):
    """Always reset vault status to 'active' after each test."""
    yield
    client.post("/vault/reset-status", headers=auth)


class TestTriggerAuth:
    def test_status_requires_auth(self, client):
        assert client.get("/vault/status").status_code == 401

    def test_trigger_requires_auth(self, client):
        assert client.post("/vault/trigger").status_code == 401

    def test_reset_requires_auth(self, client):
        assert client.post("/vault/reset-status").status_code == 401


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
        res = client.post("/vault/trigger", headers=auth)
        assert res.status_code == 200
        data = res.json()
        assert "triggered_at" in data
        assert data["triggered_at"] is not None

    def test_trigger_sets_status(self, client, auth):
        client.post("/vault/trigger", headers=auth)
        status = client.get("/vault/status", headers=auth).json()
        assert status["status"] == "triggered"
        assert status["triggered_at"] is not None

    def test_trigger_timestamp_valid_iso(self, client, auth):
        from datetime import datetime
        res = client.post("/vault/trigger", headers=auth).json()
        # Should parse without exception
        datetime.fromisoformat(res["triggered_at"].replace("Z", "+00:00"))

    def test_trigger_idempotent_returns_409(self, client, auth):
        client.post("/vault/trigger", headers=auth)
        second = client.post("/vault/trigger", headers=auth)
        assert second.status_code == 409
        assert "already been triggered" in second.json()["detail"].lower()


class TestVaultReset:
    def test_reset_returns_active(self, client, auth):
        client.post("/vault/trigger", headers=auth)
        res = client.post("/vault/reset-status", headers=auth)
        assert res.status_code == 200
        status = client.get("/vault/status", headers=auth).json()
        assert status["status"] == "active"
        assert status["triggered_at"] is None
        assert status["grace_started_at"] is None
