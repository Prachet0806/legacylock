"""Pure unit tests for Shamir's Secret Sharing — no HTTP, no DB."""

import base64
import itertools

import pytest

from services.shamir import reconstruct_secret, split_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _try_all_combos(secret: bytes, n: int, k: int):
    """Reconstruct secret from every possible k-of-n combination."""
    shares = split_secret(secret, n, k)
    for picked in itertools.combinations(shares, k):
        result = reconstruct_secret(list(picked))
        assert result == secret, f"Combo failed for share indices {[s[0] for s in picked]}"


# ---------------------------------------------------------------------------
# Core round-trip tests
# ---------------------------------------------------------------------------

class TestShamirRoundTrip:

    def test_2_of_3(self):
        secret = b"hello world secret"
        shares = split_secret(secret, n=3, k=2)
        assert len(shares) == 3
        recovered = reconstruct_secret(shares[:2])
        assert recovered == secret

    def test_3_of_5(self):
        secret = b"another test secret for 3-of-5"
        shares = split_secret(secret, n=5, k=3)
        assert len(shares) == 5
        recovered = reconstruct_secret(shares[1:4])
        assert recovered == secret

    def test_all_combos_2_of_3(self):
        """Every 2-share combo from 3 must reconstruct correctly."""
        secret = b"test key data"
        _try_all_combos(secret, n=3, k=2)

    def test_all_combos_3_of_5(self):
        """Every 3-share combo from 5 must reconstruct correctly."""
        secret = b"five share secret"
        _try_all_combos(secret, n=5, k=3)

    def test_single_byte_secret(self):
        secret = bytes([0xAB])
        shares = split_secret(secret, n=3, k=2)
        assert reconstruct_secret(shares[:2]) == secret

    def test_32_byte_aes_key(self):
        """Full AES-256 key (32 bytes) splits and reconstructs."""
        import secrets as std_secrets
        secret = std_secrets.token_bytes(32)
        shares = split_secret(secret, n=3, k=2)
        assert reconstruct_secret(shares[:2]) == secret

    def test_max_shares(self):
        """n=255 is the maximum allowed."""
        secret = b"big split"
        shares = split_secret(secret, n=255, k=2)
        assert len(shares) == 255
        assert reconstruct_secret(shares[:2]) == secret

    def test_share_indices_sequential(self):
        """First byte of each share must be its 1-based index."""
        shares = split_secret(b"index test", n=4, k=2)
        for i, share in enumerate(shares):
            assert share[0] == i + 1, f"Share {i} has wrong index byte {share[0]}"

    def test_share_length(self):
        """Each share is 1 (index) + len(secret) bytes."""
        secret = b"length check"
        shares = split_secret(secret, n=3, k=2)
        for share in shares:
            assert len(share) == 1 + len(secret)


# ---------------------------------------------------------------------------
# Security properties
# ---------------------------------------------------------------------------

class TestShamirSecurity:

    def test_fewer_than_k_gives_wrong_result(self):
        """k-1 shares must NOT reconstruct the correct secret."""
        secret = b"do not reconstruct with k-1"
        shares = split_secret(secret, n=3, k=2)
        # With only 1 share we cannot interpolate correctly (need ≥ 2)
        # reconstruct_secret() needs ≥ 2 shares — should raise, not silently succeed
        with pytest.raises((ValueError, AssertionError)):
            result = reconstruct_secret(shares[:1])

    def test_shares_are_random(self):
        """Two splits of the same secret should produce different shares."""
        secret = b"same secret"
        shares_a = split_secret(secret, n=3, k=2)
        shares_b = split_secret(secret, n=3, k=2)
        # Shares differ (overwhelmingly likely with random polynomials)
        assert shares_a[0] != shares_b[0]

    def test_order_independent(self):
        """Shares can be passed in any order."""
        secret = b"order does not matter"
        shares = split_secret(secret, n=3, k=2)
        assert reconstruct_secret([shares[1], shares[0]]) == secret


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestShamirValidation:

    def test_k_greater_than_n_raises(self):
        with pytest.raises(ValueError, match="Invalid parameters"):
            split_secret(b"test", n=2, k=3)

    def test_k_equals_one_raises(self):
        with pytest.raises(ValueError, match="Invalid parameters"):
            split_secret(b"test", n=3, k=1)

    def test_n_exceeds_255_raises(self):
        with pytest.raises(ValueError, match="Invalid parameters"):
            split_secret(b"test", n=256, k=2)

    def test_reconstruct_requires_two_shares(self):
        with pytest.raises(ValueError, match="at least 2 shares"):
            reconstruct_secret([b"\x01hello"])

    def test_reconstruct_mismatched_lengths(self):
        shares = split_secret(b"abc", n=2, k=2)
        # Corrupt second share to be a different length
        bad = bytes([shares[1][0]]) + b"toolong!!!"
        with pytest.raises(ValueError, match="same length"):
            reconstruct_secret([shares[0], bad])
