"""Tests for per-vault Shamir k-of-n recovery policy + ceremony binding."""

import secrets

GEN_A = secrets.token_hex(16)
GEN_B = secrets.token_hex(16)
GEN_C = secrets.token_hex(16)
GEN_D = secrets.token_hex(16)
GEN_E = secrets.token_hex(16)
GEN_F = secrets.token_hex(16)


class TestRecoveryPolicy:
    def test_defaults_are_2_of_3(self, client, auth):
        res = client.get("/vault/recovery-policy", headers=auth)
        assert res.status_code == 200
        body = res.json()
        assert body["recovery_threshold"] == 2
        assert body["recovery_total"] == 3

    def test_ceremony_sets_policy_and_generation(self, client, auth):
        res = client.post(
            "/vault/recovery-ceremony",
            json={"recovery_threshold": 3, "recovery_total": 5, "recovery_generation": GEN_A},
            headers=auth,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["recovery_generation"] == GEN_A
        assert body["recovery_status"] == "READY"
        got = client.get("/vault/recovery-policy", headers=auth).json()
        assert got["recovery_threshold"] == 3
        assert got["recovery_generation"] == GEN_A

    def test_put_silent_change_rejected(self, client, auth):
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 3, "recovery_total": 5},
            headers=auth,
        )
        assert res.status_code == 409

    def test_put_same_policy_noop(self, client, auth):
        res = client.put(
            "/vault/recovery-policy",
            json={"recovery_threshold": 2, "recovery_total": 3},
            headers=auth,
        )
        assert res.status_code == 200

    def test_ceremony_generation_reuse_rejected(self, client, auth):
        assert (
            client.post(
                "/vault/recovery-ceremony",
                json={
                    "recovery_threshold": 2,
                    "recovery_total": 3,
                    "recovery_generation": GEN_B,
                },
                headers=auth,
            ).status_code
            == 200
        )
        res = client.post(
            "/vault/recovery-ceremony",
            json={"recovery_threshold": 2, "recovery_total": 3, "recovery_generation": GEN_B},
            headers=auth,
        )
        assert res.status_code == 409

    def test_small_n_allowed(self, client, auth):
        res = client.post(
            "/vault/recovery-ceremony",
            json={"recovery_threshold": 2, "recovery_total": 2, "recovery_generation": GEN_C},
            headers=auth,
        )
        assert res.status_code == 200

    def test_single_share_allowed(self, client, auth):
        # 1-of-n kept by product decision (single share recovers — warn in UI).
        res = client.post(
            "/vault/recovery-ceremony",
            json={"recovery_threshold": 1, "recovery_total": 1, "recovery_generation": GEN_D},
            headers=auth,
        )
        assert res.status_code == 200

    def test_threshold_above_total_rejected(self, client, auth):
        res = client.post(
            "/vault/recovery-ceremony",
            json={
                "recovery_threshold": 4,
                "recovery_total": 3,
                "recovery_generation": secrets.token_hex(16),
            },
            headers=auth,
        )
        assert res.status_code == 422

    def test_share_index_bounded_by_policy(self, client, auth):
        client.post(
            "/vault/recovery-ceremony",
            json={"recovery_threshold": 2, "recovery_total": 5, "recovery_generation": GEN_E},
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
        client.post(
            "/vault/recovery-ceremony",
            json={"recovery_threshold": 2, "recovery_total": 5, "recovery_generation": GEN_F},
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
        res = client.post(
            "/vault/recovery-ceremony",
            json={
                "recovery_threshold": 2,
                "recovery_total": 3,
                "recovery_generation": secrets.token_hex(16),
            },
            headers=auth,
        )
        assert res.status_code == 409

    def test_crypto_material_policy_change_requires_generation(self, client, auth):
        import base64

        wrapped = base64.b64encode(b"0" * 48).decode()
        salt = base64.b64encode(b"1" * 16).decode()
        base = {
            "wrapped_vmk": wrapped,
            "vmk_crypto_version": 1,
            "vmk_kdf_algorithm": "PBKDF2-SHA256",
            "vmk_kdf_salt": salt,
            "vmk_kdf_parameters": {"iterations": 600000},
        }
        # Silent k/n change without generation -> 409.
        res = client.put(
            "/vault/crypto-material",
            json={**base, "recovery_threshold": 3, "recovery_total": 5},
            headers=auth,
        )
        assert res.status_code == 409
        # With fresh generation -> 200.
        gen = secrets.token_hex(16)
        res = client.put(
            "/vault/crypto-material",
            json={
                **base,
                "recovery_threshold": 3,
                "recovery_total": 5,
                "recovery_generation": gen,
            },
            headers=auth,
        )
        assert res.status_code == 200
        got = client.get("/vault/recovery-policy", headers=auth).json()
        assert got["recovery_threshold"] == 3
        assert got["recovery_generation"] == gen
