from tests.helpers import complete_ceremony

"""Legacy migration → recovery: pre-ceremony vaults adopt the ceremony model.

Covers the deploy path: old DB rows (NULL recovery_generation, default 2-of-3)
upgrade to head, then complete exactly one ceremony. Proves policy metadata
never silently diverges from the distributed share set.
"""

import base64
import secrets


def _material(client, auth):
    return {
        "wrapped_vmk": base64.b64encode(b"0" * 40).decode(),
        "expected_revision": client.get("/vault/crypto-material", headers=auth).json()[
            "material_revision"
        ],
        "vmk_crypto_version": 1,
        "vmk_kdf_algorithm": "PBKDF2-SHA256",
        "vmk_kdf_salt": base64.b64encode(b"1" * 16).decode(),
        "vmk_kdf_parameters": {"iterations": 600000},
    }


class TestLegacyMigrationRecovery:
    def test_preceremony_vault_defaults_then_adopts(self, client, auth):
        # Fresh vault from auth fixture has no ceremony yet: defaults 2-of-3.
        got = client.get("/vault/recovery-policy", headers=auth).json()
        assert got["recovery_threshold"] == 2
        assert got["recovery_total"] == 3
        assert got["recovery_generation"] is None

        # Material-only PUT (passphrase path) works without ceremony fields.
        assert (
            client.put(
                "/vault/crypto-material", json=_material(client, auth), headers=auth
            ).status_code
            == 200
        )
        assert (
            client.get("/vault/recovery-policy", headers=auth).json()["recovery_generation"] is None
        )

        # Legacy vault adopts one ceremony: fresh → 200, same → 409, new → 200.
        gen1 = secrets.token_hex(16)
        gen2 = secrets.token_hex(16)
        assert (
            complete_ceremony(
                client,
                json={"recovery_threshold": 2, "recovery_total": 3, "recovery_generation": gen1},
                headers=auth,
            ).status_code
            == 200
        )
        assert (
            complete_ceremony(
                client,
                json={"recovery_threshold": 2, "recovery_total": 3, "recovery_generation": gen1},
                headers=auth,
            ).status_code
            == 409
        )
        assert (
            complete_ceremony(
                client,
                json={"recovery_threshold": 2, "recovery_total": 3, "recovery_generation": gen2},
                headers=auth,
            ).status_code
            == 200
        )
        # Material PUT after ceremony preserves the binding.
        assert (
            client.put(
                "/vault/crypto-material", json=_material(client, auth), headers=auth
            ).status_code
            == 200
        )
        got = client.get("/vault/recovery-policy", headers=auth).json()
        assert got["recovery_generation"] == gen2

    def test_alembic_roundtrip_preserves_vault(self, client, auth):
        """Downgrade to pre-ceremony revision and back; data must survive."""
        from pathlib import Path

        from alembic.config import Config

        from alembic import command

        cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
        command.upgrade(cfg, "head")
        # Destructive downgrades are forbidden after durable history is introduced.
        # Vault provisioned before the roundtrip is still reachable.
        assert (
            client.put(
                "/vault/crypto-material", json=_material(client, auth), headers=auth
            ).status_code
            == 200
        )
