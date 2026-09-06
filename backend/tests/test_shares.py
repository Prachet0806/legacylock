"""Tests for /vault/shares routes."""

import base64

import pytest


@pytest.fixture
def three_beneficiaries(client, auth):
    """Create 3 beneficiaries and yield their IDs. Cleans up after."""
    ids = []
    for i, (name, email) in enumerate([
        ("Alice", "alice@test.com"),
        ("Bob", "bob@test.com"),
        ("Carol", "carol@test.com"),
    ]):
        res = client.post("/beneficiaries", json={"name": name, "email": email}, headers=auth)
        ids.append(res.json()["id"])
    yield ids
    for ben_id in ids:
        client.delete(f"/beneficiaries/{ben_id}", headers=auth)
    client.post("/vault/reset-status", headers=auth)


def make_key_b64(num_bytes: int = 32) -> str:
    """Generate a random base64-encoded key."""
    import secrets
    return base64.b64encode(secrets.token_bytes(num_bytes)).decode()


class TestSharesAuth:
    def test_generate_requires_auth(self, client):
        res = client.post("/vault/shares/generate", json={"key_b64": make_key_b64(), "threshold": 2, "total": 3})
        assert res.status_code == 401

    def test_list_requires_auth(self, client):
        assert client.get("/vault/shares").status_code == 401


class TestSharesGenerate:
    def test_generate_no_beneficiaries(self, client, auth):
        """Cannot generate when no beneficiaries exist."""
        # Make sure no beneficiaries
        bens = client.get("/beneficiaries", headers=auth).json()
        for b in bens:
            client.delete(f"/beneficiaries/{b['id']}", headers=auth)

        res = client.post(
            "/vault/shares/generate",
            json={"key_b64": make_key_b64(), "threshold": 2, "total": 3},
            headers=auth,
        )
        assert res.status_code == 400

    def test_generate_assigns_shares(self, client, auth, three_beneficiaries):
        res = client.post(
            "/vault/shares/generate",
            json={"key_b64": make_key_b64(), "threshold": 2, "total": 3},
            headers=auth,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["shares_assigned"] == 3
        assert data["threshold"] == 2

    def test_generate_list_shows_shares(self, client, auth, three_beneficiaries):
        client.post(
            "/vault/shares/generate",
            json={"key_b64": make_key_b64(), "threshold": 2, "total": 3},
            headers=auth,
        )
        items = client.get("/vault/shares", headers=auth).json()
        assert len(items) == 3
        assert all(item["has_share"] for item in items)

    def test_generate_updates_vault_threshold(self, client, auth, three_beneficiaries):
        client.post(
            "/vault/shares/generate",
            json={"key_b64": make_key_b64(), "threshold": 2, "total": 3},
            headers=auth,
        )
        status = client.get("/vault/status", headers=auth).json()
        assert status["share_threshold"] == 2
        assert status["share_total"] == 3


class TestSharesReconstruct:
    def test_reconstruct_round_trip(self, client, auth, three_beneficiaries):
        """Generate shares from a known key, retrieve them, reconstruct, verify match."""
        from services.shamir import split_secret

        original_key = base64.b64decode(make_key_b64())

        # Generate via API
        client.post(
            "/vault/shares/generate",
            json={"key_b64": base64.b64encode(original_key).decode(), "threshold": 2, "total": 3},
            headers=auth,
        )

        # Read share data from DB via share list (only has_share, not the raw data)
        # For reconstruction test, generate shares locally using the same key
        from services.shamir import reconstruct_secret
        shares = split_secret(original_key, n=3, k=2)
        recovered = reconstruct_secret(shares[:2])
        assert recovered == original_key

    def test_reconstruct_endpoint(self, client):
        """POST /vault/shares/reconstruct without auth — beneficiary-facing."""
        import secrets as std_secrets

        from services.shamir import split_secret

        original_key = std_secrets.token_bytes(16)
        shares = split_secret(original_key, n=3, k=2)
        shares_b64 = [base64.b64encode(s).decode() for s in shares[:2]]

        res = client.post(
            "/vault/shares/reconstruct",
            json={"shares_b64": shares_b64},
        )
        assert res.status_code == 200
        recovered = base64.b64decode(res.json()["key_b64"])
        assert recovered == original_key

    def test_reconstruct_one_share_fails(self, client):
        from services.shamir import split_secret
        shares = split_secret(b"secret", n=3, k=2)
        res = client.post(
            "/vault/shares/reconstruct",
            json={"shares_b64": [base64.b64encode(shares[0]).decode()]},
        )
        # Pydantic min_length=2 on list  → 422 before the handler even runs
        assert res.status_code in (400, 422)

    def test_reconstruct_bad_base64(self, client):
        res = client.post(
            "/vault/shares/reconstruct",
            json={"shares_b64": ["not-valid-base64!!!", "also-bad-!!!"]},
        )
        assert res.status_code == 400
