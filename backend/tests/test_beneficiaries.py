"""Tests for /beneficiaries routes."""

import pytest


@pytest.fixture(autouse=True)
def clean_beneficiaries(client, auth):
    """Delete all beneficiaries before each test."""
    res = client.get("/beneficiaries", headers=auth)
    for b in res.json():
        client.delete(f"/beneficiaries/{b['id']}", headers=auth)
    yield
    res = client.get("/beneficiaries", headers=auth)
    for b in res.json():
        client.delete(f"/beneficiaries/{b['id']}", headers=auth)


class TestBeneficiaryAuth:
    def test_add_requires_auth(self, client):
        res = client.post("/beneficiaries", json={"name": "Alice", "email": "a@b.com"})
        assert res.status_code == 401

    def test_list_requires_auth(self, client):
        assert client.get("/beneficiaries").status_code == 401

    def test_delete_requires_auth(self, client):
        assert client.delete("/beneficiaries/1").status_code == 401


class TestBeneficiaryCRUD:
    def test_add_beneficiary(self, client, auth):
        res = client.post("/beneficiaries", json={"name": "Alice", "email": "alice@test.com"}, headers=auth)
        assert res.status_code == 201
        assert "id" in res.json()

    def test_add_with_phone(self, client, auth):
        res = client.post(
            "/beneficiaries",
            json={"name": "Bob", "email": "bob@test.com", "phone": "+15551234567"},
            headers=auth,
        )
        assert res.status_code == 201
        ben_id = res.json()["id"]
        # Verify phone is stored in list
        items = client.get("/beneficiaries", headers=auth).json()
        match = next((b for b in items if b["id"] == ben_id), None)
        assert match is not None
        assert match["phone"] == "+15551234567"

    def test_list_beneficiaries(self, client, auth):
        client.post("/beneficiaries", json={"name": "Alice", "email": "a@t.com"}, headers=auth)
        client.post("/beneficiaries", json={"name": "Bob", "email": "b@t.com"}, headers=auth)
        res = client.get("/beneficiaries", headers=auth)
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_list_empty(self, client, auth):
        res = client.get("/beneficiaries", headers=auth)
        assert res.status_code == 200
        assert res.json() == []

    def test_phone_optional(self, client, auth):
        client.post("/beneficiaries", json={"name": "Alice", "email": "a@t.com"}, headers=auth)
        items = client.get("/beneficiaries", headers=auth).json()
        assert items[0]["phone"] is None

    def test_delete_beneficiary(self, client, auth):
        post = client.post("/beneficiaries", json={"name": "Alice", "email": "a@t.com"}, headers=auth)
        ben_id = post.json()["id"]
        res = client.delete(f"/beneficiaries/{ben_id}", headers=auth)
        assert res.status_code == 204
        items = client.get("/beneficiaries", headers=auth).json()
        assert not any(b["id"] == ben_id for b in items)

    def test_delete_not_found(self, client, auth):
        res = client.delete("/beneficiaries/99999", headers=auth)
        assert res.status_code == 404

    def test_response_includes_all_fields(self, client, auth):
        client.post("/beneficiaries", json={"name": "Alice", "email": "a@t.com", "phone": "123"}, headers=auth)
        item = client.get("/beneficiaries", headers=auth).json()[0]
        for field in ("id", "name", "email", "phone", "created_at"):
            assert field in item


class TestBeneficiaryValidation:
    def test_name_required(self, client, auth):
        res = client.post("/beneficiaries", json={"email": "a@b.com"}, headers=auth)
        assert res.status_code == 422

    def test_email_required(self, client, auth):
        res = client.post("/beneficiaries", json={"name": "Alice"}, headers=auth)
        assert res.status_code == 422

    def test_name_too_long(self, client, auth):
        res = client.post(
            "/beneficiaries",
            json={"name": "x" * 201, "email": "a@b.com"},
            headers=auth,
        )
        assert res.status_code == 422

    def test_phone_too_long(self, client, auth):
        res = client.post(
            "/beneficiaries",
            json={"name": "Alice", "email": "a@b.com", "phone": "1" * 31},
            headers=auth,
        )
        assert res.status_code == 422
