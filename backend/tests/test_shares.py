"""Tests for /vault/shares routes (client-side Shamir; server stores only)."""

import base64
import secrets

import pytest


def make_b64(num_bytes: int = 32) -> str:
    return base64.b64encode(secrets.token_bytes(num_bytes)).decode()


@pytest.fixture
def three_beneficiaries(client, auth):
    """Create 3 accepted beneficiaries for share assignment."""
    ids = []
    for name, email in [("Alice", "alice@test.com"), ("Bob", "bob@test.com"), ("Carol", "carol@test.com")]:
        res = client.post("/beneficiaries", json={"name": name, "email": email}, headers=auth)
        ids.append(res.json()["id"])
        # Invite + accept via API to reach accepted state
        inv = client.post(f"/beneficiaries/{ids[-1]}/invite", headers=auth)
        assert inv.status_code == 200
        link = inv.json()["invitation_link"]
        ihash = link.rsplit("/", 1)[-1]
        acc = client.post(f"/access/invite/{ihash}/accept")
        assert acc.status_code == 200
    yield ids
    for ben_id in ids:
        client.delete(f"/beneficiaries/{ben_id}", headers=auth)


class TestSharesAuth:
    def test_config_requires_auth(self, client):
        assert client.get("/vault/shares/config").status_code == 401

    def test_list_requires_auth(self, client):
        assert client.get("/vault/shares").status_code == 401


class TestShareConfig:
    def test_set_and_get_config(self, client, auth):
        res = client.post("/vault/shares/config", json={"threshold": 2, "total": 3}, headers=auth)
        assert res.status_code == 200
        assert res.json() == {"threshold": 2, "total": 3}
        got = client.get("/vault/shares/config", headers=auth).json()
        assert got == {"threshold": 2, "total": 3}

    def test_threshold_exceeds_total_rejected(self, client, auth):
        res = client.post("/vault/shares/config", json={"threshold": 5, "total": 3}, headers=auth)
        assert res.status_code == 422


class TestEncryptedShares:
    def test_assign_and_list(self, client, auth, three_beneficiaries):
        ben_id = three_beneficiaries[0]
        res = client.post(
            "/vault/shares/encrypted-shares",
            json={"beneficiary_id": ben_id, "encrypted_share_b64": make_b64(), "share_index": 1},
            headers=auth,
        )
        assert res.status_code == 200
        items = client.get("/vault/shares", headers=auth).json()
        assert len(items) == 3
        match = next(i for i in items if i["beneficiary_id"] == ben_id)
        assert match["has_encrypted_share"] is True

    def test_assign_bad_base64(self, client, auth, three_beneficiaries):
        res = client.post(
            "/vault/shares/encrypted-shares",
            json={"beneficiary_id": three_beneficiaries[0], "encrypted_share_b64": "!!!", "share_index": 1},
            headers=auth,
        )
        assert res.status_code == 422

    def test_assign_unknown_beneficiary(self, client, auth):
        res = client.post(
            "/vault/shares/encrypted-shares",
            json={"beneficiary_id": 999999, "encrypted_share_b64": make_b64(), "share_index": 1},
            headers=auth,
        )
        assert res.status_code == 404


class TestSharesReconstruct:
    def test_reconstruct_round_trip(self):
        from services.shamir import split_secret, reconstruct_secret

        original = secrets.token_bytes(16)
        shares = split_secret(original, n=3, k=2)
        assert reconstruct_secret(shares[:2]) == original

    def test_reconstruct_endpoint(self, client):
        from services.shamir import split_secret

        original = secrets.token_bytes(16)
        shares = split_secret(original, n=3, k=2)
        shares_b64 = [base64.b64encode(s).decode() for s in shares[:2]]

        res = client.post("/vault/shares/reconstruct", json={"shares_b64": shares_b64})
        assert res.status_code == 200
        assert base64.b64decode(res.json()["key_b64"]) == original

    def test_reconstruct_one_share_fails(self, client):
        from services.shamir import split_secret
        shares = split_secret(b"secret", n=3, k=2)
        res = client.post(
            "/vault/shares/reconstruct",
            json={"shares_b64": [base64.b64encode(shares[0]).decode()]},
        )
        assert res.status_code in (400, 422)

    def test_reconstruct_bad_base64(self, client):
        res = client.post(
            "/vault/shares/reconstruct",
            json={"shares_b64": ["not-valid-base64!!!", "also-bad-!!!"]},
        )
        assert res.status_code == 400
