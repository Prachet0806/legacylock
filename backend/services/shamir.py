"""Shamir's Secret Sharing over GF(256).

This implements a simple and correct (k, n) threshold secret sharing scheme
over the Galois Field GF(2^8). Each byte of the secret is independently
split, producing n shares of the same length as the secret.

Any k shares can reconstruct the secret; fewer than k shares reveal nothing.
"""

import secrets

# ---------------------------------------------------------------------------
# GF(256) arithmetic — using the AES irreducible polynomial x^8+x^4+x^3+x+1
# ---------------------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256

_g = 1
for i in range(255):
    _EXP[i] = _g
    _EXP[i + 255] = _g
    _LOG[_g] = i
    _g = (_g << 1) ^ _g
    if _g & 0x100:
        _g ^= 0x11B  # AES polynomial

_EXP[510] = _EXP[0]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _gf_inv(a: int) -> int:
    if a == 0:
        raise ValueError("Cannot invert zero in GF(256)")
    return _EXP[255 - _LOG[a]]


# ---------------------------------------------------------------------------
# Polynomial evaluation and Lagrange interpolation
# ---------------------------------------------------------------------------

def _eval_poly(coeffs: list[int], x: int) -> int:
    """Evaluate polynomial at x in GF(256). coeffs[0] = constant term."""
    result = 0
    for i in range(len(coeffs) - 1, -1, -1):
        result = _gf_mul(result, x) ^ coeffs[i]
    return result


def _lagrange_interpolate(shares: list[tuple[int, int]]) -> int:
    """Recover the secret (constant term) from k shares using Lagrange interpolation."""
    k = len(shares)
    secret = 0

    for i in range(k):
        xi, yi = shares[i]
        basis = yi

        for j in range(k):
            if i == j:
                continue
            xj, _ = shares[j]
            # basis *= xj / (xi ^ xj)
            num = xj
            den = xi ^ xj
            basis = _gf_mul(basis, _gf_mul(num, _gf_inv(den)))

        secret ^= basis

    return secret


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def split_secret(secret: bytes, n: int, k: int) -> list[bytes]:
    """Split a secret into n shares, requiring k to reconstruct.

    Args:
        secret: The secret bytes to split.
        n: Total number of shares (2 ≤ n ≤ 255).
        k: Threshold for reconstruction (2 ≤ k ≤ n).

    Returns:
        List of n share byte strings, each the same length as secret.
        Share indices are 1..n (stored as first byte of each share).
    """
    if not (2 <= k <= n <= 255):
        raise ValueError(f"Invalid parameters: k={k}, n={n}. Need 2 ≤ k ≤ n ≤ 255.")

    shares = [bytearray() for _ in range(n)]

    for byte_val in secret:
        # Random polynomial of degree k-1 with constant term = byte_val
        coeffs = [byte_val] + [secrets.randbelow(256) for _ in range(k - 1)]

        for i in range(n):
            x = i + 1  # share indices 1..n
            y = _eval_poly(coeffs, x)
            shares[i].append(y)

    # Prepend share index
    result = []
    for i in range(n):
        share = bytearray([i + 1]) + shares[i]
        result.append(bytes(share))

    return result


def reconstruct_secret(shares: list[bytes]) -> bytes:
    """Reconstruct a secret from k shares.

    Args:
        shares: List of k share byte strings (each starts with 1-byte index).

    Returns:
        The reconstructed secret bytes.
    """
    if len(shares) < 2:
        raise ValueError("Need at least 2 shares to reconstruct.")

    # Parse: first byte is index, rest is share data
    parsed = [(s[0], s[1:]) for s in shares]
    data_len = len(parsed[0][1])

    if any(len(d) != data_len for _, d in parsed):
        raise ValueError("All shares must be the same length.")

    secret = bytearray()
    for byte_idx in range(data_len):
        points = [(x, d[byte_idx]) for x, d in parsed]
        secret.append(_lagrange_interpolate(points))

    return bytes(secret)
