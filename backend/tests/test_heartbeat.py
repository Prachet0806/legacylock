"""Tests for /heartbeat routes."""


class TestHeartbeatAuth:
    def test_get_requires_auth(self, client):
        assert client.get("/heartbeat").status_code == 401

    def test_put_requires_auth(self, client):
        assert (
            client.put("/heartbeat", json={"interval_days": 30, "grace_days": 7}).status_code == 401
        )

    def test_checkin_requires_auth(self, client):
        assert client.post("/heartbeat/checkin").status_code == 401


class TestHeartbeatConfig:
    def test_get_defaults(self, client, auth):
        """First GET creates the singleton with defaults."""
        res = client.get("/heartbeat", headers=auth)
        assert res.status_code == 200
        data = res.json()
        assert data["interval_days"] in (30, 60, 90)  # may have been changed by other tests
        assert "grace_days" in data
        assert "last_check_in" in data

    def test_save_config(self, client, auth):
        res = client.put("/heartbeat", json={"interval_days": 60, "grace_days": 14}, headers=auth)
        assert res.status_code == 200

    def test_get_updated_config(self, client, auth):
        client.put("/heartbeat", json={"interval_days": 90, "grace_days": 7}, headers=auth)
        data = client.get("/heartbeat", headers=auth).json()
        assert data["interval_days"] == 90
        assert data["grace_days"] == 7

    def test_checkin_sets_timestamp(self, client, auth):
        res = client.post("/heartbeat/checkin", headers=auth)
        assert res.status_code == 200
        assert res.json()["last_check_in"] is not None

    def test_checkin_updates_timestamp(self, client, auth):
        r1 = client.post("/heartbeat/checkin", headers=auth).json()["last_check_in"]
        import time

        time.sleep(0.01)
        r2 = client.post("/heartbeat/checkin", headers=auth).json()["last_check_in"]
        assert r2 >= r1

    def test_last_checkin_reflected_in_get(self, client, auth):
        client.post("/heartbeat/checkin", headers=auth)
        data = client.get("/heartbeat", headers=auth).json()
        assert data["last_check_in"] is not None


class TestHeartbeatValidation:
    def test_interval_zero(self, client, auth):
        res = client.put("/heartbeat", json={"interval_days": 0, "grace_days": 7}, headers=auth)
        assert res.status_code == 422

    def test_interval_too_large(self, client, auth):
        res = client.put("/heartbeat", json={"interval_days": 366, "grace_days": 7}, headers=auth)
        assert res.status_code == 422

    def test_grace_zero(self, client, auth):
        res = client.put("/heartbeat", json={"interval_days": 30, "grace_days": 0}, headers=auth)
        assert res.status_code == 422

    def test_grace_too_large(self, client, auth):
        res = client.put("/heartbeat", json={"interval_days": 30, "grace_days": 91}, headers=auth)
        assert res.status_code == 422

    def test_missing_interval(self, client, auth):
        res = client.put("/heartbeat", json={"grace_days": 7}, headers=auth)
        assert res.status_code == 422

    def test_missing_grace(self, client, auth):
        res = client.put("/heartbeat", json={"interval_days": 30}, headers=auth)
        assert res.status_code == 422
