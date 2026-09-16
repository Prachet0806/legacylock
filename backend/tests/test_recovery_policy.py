"""Tests for per-vault Shamir k-of-n recovery policy."""


class TestRecoveryPolicy:
    def test_defaults_are_2_of_3(self, client, auth):
        res = client.get("/vault/recovery-policy", headers=auth)
        assert res.status_code == 200
        assert res.json() == {"recovery_threshold": 2, "recovery_total": 3}

    def test_put_valid_policy(self, client, auth):
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 3, "recovery_total": 5},
            headers=auth,
        )
        assert res.status_code == 200
        assert res.json() == {"recovery_threshold": 3, "recovery_total": 5}
        assert client.get("/vault/recovery-policy", headers=auth).json()["recovery_total"] == 5

    def test_small_n_allowed(self, client, auth):
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 2, "recovery_total": 2},
            headers=auth,
        )
        assert res.status_code == 200

    def test_single_share_allowed(self, client, auth):
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 1, "recovery_total": 1},
            headers=auth,
        )
        assert res.status_code == 200

    def test_threshold_above_total_rejected(self, client, auth):
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 4, "recovery_total": 3},
            headers=auth,
        )
        assert res.status_code == 422

    def test_status_includes_policy(self, client, auth):
        client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 2, "recovery_total": 5},
            headers=auth,
        )
        res = client.get("/vault/status", headers=auth)
        assert res.status_code == 200
        body = res.json()
        assert body["recovery_threshold"] == 2
        assert body["recovery_total"] == 5

    def test_share_index_bounded_by_policy(self, client, auth):
        client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 2, "recovery_total": 5},
            headers=auth,
        )
        post = client.post(
            "/beneficiaries", json={"name": "A", "email": "a@t.com"}, headers=auth
        )
        assert post.status_code == 201
        ben_id = post.json()["id"]
        ok = client.post(f"/beneficiaries/{ben_id}/assign-share", json={"share_index": 5}, headers=auth)
        assert ok.status_code == 200
        bad = client.post(f"/beneficiaries/{ben_id}/assign-share", json={"share_index": 6}, headers=auth)
        assert bad.status_code == 422

    def test_shrinking_total_below_assignment_rejected(self, client, auth):
        client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 2, "recovery_total": 5},
            headers=auth,
        )
        post = client.post(
            "/beneficiaries", json={"name": "A", "email": "a@t.com"}, headers=auth
        )
        ben_id = post.json()["id"]
        assert (
            client.post(
                f"/beneficiaries/{ben_id}/assign-share", json={"share_index": 5}, headers=auth
            ).status_code
            == 200
        )
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 2, "recovery_total": 3},
            headers=auth,
        )
        assert res.status_code == 409

    def test_crypto_material_accepts_policy(self, client, auth):
        import base64

        wrapped = base64.b64encode(b"0" * 48).decode()
        salt = base64.b64encode(b"1" * 16).decode()
        res = client.put(
            "/vault/crypto-material",
            json={
                "wrapped_vmk": wrapped,
                "vmk_crypto_version": 1,
                "vmk_kdf_algorithm": "PBKDF2-SHA256",
                "vmk_kdf_salt": salt,
                "vmk_kdf_parameters": {"iterations": 600000},
                "recovery_threshold": 3,
                "recovery_total": 5,
            },
            headers=auth,
        )
        assert res.status_code == 200
        assert client.get("/vault/recovery-policy", headers=auth).json() == {
            "recovery_threshold": 3,
            "recovery_total": 5,
        }
