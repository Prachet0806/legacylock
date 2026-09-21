"""Tests for POST /heartbeat/run-check (non-production time-travel driver).

Proves ACTIVE -> GRACE -> TRIGGERED with realistic day-granularity config
(30/7) without waiting out real deadlines.
"""


class TestRunCheckAuth:
    def test_requires_auth(self, client):
        assert client.post("/heartbeat/run-check", json={"advance_days": 31}).status_code == 401


class TestRunCheckValidation:
    def test_negative_advance_rejected(self, client, auth):
        res = client.post("/heartbeat/run-check", json={"advance_days": -1}, headers=auth)
        assert res.status_code == 422

    def test_huge_advance_rejected(self, client, auth):
        res = client.post("/heartbeat/run-check", json={"advance_days": 99999}, headers=auth)
        assert res.status_code == 422


class TestRunCheckAutoTrigger:
    def _setup(self, client, auth):
        assert (
            client.put("/heartbeat", json={"interval_days": 30, "grace_days": 7}, headers=auth).status_code
            == 200
        )
        assert client.post("/heartbeat/checkin", headers=auth).status_code == 200

    def test_no_advance_no_transition(self, client, auth):
        self._setup(client, auth)
        res = client.post("/heartbeat/run-check", json={"advance_days": 0}, headers=auth)
        assert res.status_code == 200
        assert res.json()["actions"] == []
        assert client.get("/vault/status", headers=auth).json()["status"] == "active"

    def test_full_auto_trigger_lifecycle(self, client, auth):
        self._setup(client, auth)

        # 31 simulated days past a 30-day interval -> GRACE.
        res = client.post("/heartbeat/run-check", json={"advance_days": 31}, headers=auth)
        assert res.status_code == 200
        assert any("grace_started" in a for a in res.json()["actions"])
        status = client.get("/vault/status", headers=auth).json()
        assert status["status"] == "grace"
        assert status["grace_started_at"] is not None

        # A check-in cancels grace (CAS reset) -> ACTIVE.
        assert client.post("/heartbeat/checkin", headers=auth).status_code == 200
        assert client.get("/vault/status", headers=auth).json()["status"] == "active"

        # Advance past interval + grace -> TRIGGERED with inactivity reason.
        res = client.post("/heartbeat/run-check", json={"advance_days": 31}, headers=auth)
        assert any("grace_started" in a for a in res.json()["actions"])
        res = client.post("/heartbeat/run-check", json={"advance_days": 40}, headers=auth)
        assert any("triggered" in a for a in res.json()["actions"])
        status = client.get("/vault/status", headers=auth).json()
        assert status["status"] == "triggered"
        assert status["triggered_at"] is not None

    def test_trigger_idempotent(self, client, auth):
        self._setup(client, auth)
        client.post("/heartbeat/run-check", json={"advance_days": 31}, headers=auth)
        client.post("/heartbeat/run-check", json={"advance_days": 40}, headers=auth)
        first = client.get("/vault/status", headers=auth).json()["triggered_at"]
        res = client.post("/heartbeat/run-check", json={"advance_days": 40}, headers=auth)
        assert res.json()["actions"] == []
        assert client.get("/vault/status", headers=auth).json()["triggered_at"] == first

    def test_no_checkin_never_transitions(self, client, auth):
        # Config exists via GET (defaults) but no check-in recorded.
        client.get("/heartbeat", headers=auth)
        res = client.post("/heartbeat/run-check", json={"advance_days": 365}, headers=auth)
        assert res.status_code == 200
        assert res.json()["actions"] == []
        assert client.get("/vault/status", headers=auth).json()["status"] == "active"
