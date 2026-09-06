# LegacyLock — Cryptographic Design

## Key Hierarchy

```text
                 Vault Master Key (VMK)
                    /                              /                       Shamir 2-of-3       Key wrapping
              /                         Share A/B/C               MEK
                                  │
                                  ▼
                             AES-256-GCM
                                  │
                                  ▼
                              Ciphertext
```

## Secret Separation

```text
Login Password ≠ Vault Passphrase ≠ KEK ≠ VMK ≠ MEK
```

- **Login Password:** authenticates the owner account.
- **Vault Passphrase:** unlocks the vault cryptographic material locally.
- **KEK:** locally derived Key Encryption Key used only to wrap/unwrap the VMK.
- **VMK:** random high-entropy root vault key.
- **MEK:** random per-message encryption key.

The login password does not derive the VMK and is not the Shamir-split secret.

## VMK

The VMK is a randomly generated high-entropy vault key. It survives owner logout and browser refresh through client-side wrapping; only the wrapped form is persisted.

Properties:

- Generated client-side
- Never sent to backend
- Held only in memory when required
- Used to protect message encryption keys
- Split into Shamir shares

## MEK

Each message gets an independent random Message Encryption Key.

Properties:

- Generated client-side
- Random
- Used for AES-256-GCM
- Wrapped by the VMK
- Never sent to backend in plaintext

## Message Encryption

```text
Plaintext
   ↓
Random MEK
   ↓
AES-256-GCM + random IV
   ↓
Ciphertext
```

## KDF

The MVP may use PBKDF2-SHA256 with a fixed, documented iteration count.

The exact count must be recorded in the implementation and crypto test vectors.

Long-term direction: Argon2id.

## Serialization

Encrypted records must be versioned and contain enough metadata to identify:

- Crypto version
- KDF parameters where applicable
- Salt where applicable
- IV/nonce
- Ciphertext
- Wrapped MEK

Recommended conceptual format:

```text
version
algorithm
kdf metadata
salt
iv
wrapped_mek
ciphertext
```

## Shamir

MVP uses 2-of-3 Shamir's Secret Sharing over GF(256).

Reconstruction is performed exclusively in the browser.

## Share Distribution

LegacyLock does not email, SMS, or otherwise transmit raw shares.

The owner distributes shares out-of-band.

## Key Loss

There is deliberately no recovery mechanism for lost vault cryptographic material in MVP.

Losing sufficient recovery shares can make vault content permanently unrecoverable.

## Crypto Invariants

- Never persist VMK in localStorage.
- Never send VMK to backend.
- Never log cryptographic secrets.
- Never reconstruct VMK server-side.
- Never treat login-password recovery as vault-key recovery.
- Version cryptographic formats.

## VMK Persistence & Owner Unlock

The VMK cannot be deterministically regenerated from the login password. It is therefore wrapped client-side with a KEK derived from a dedicated vault passphrase.

### Initial Setup

```text
Generate random VMK
      ↓
Generate Shamir shares from VMK
      ↓
Derive KEK from vault passphrase
      ↓
Wrap VMK with KEK
      ↓
Store wrapped VMK + KDF metadata
```

### Subsequent Unlock

```text
Owner login
      ↓
Enter vault passphrase
      ↓
Derive KEK locally
      ↓
Fetch wrapped VMK
      ↓
Unwrap VMK locally
      ↓
Keep VMK in memory only
```

The backend stores the wrapped VMK and non-secret KDF metadata. It never receives the vault passphrase, KEK, or unwrapped VMK.

### VMK Storage Rules

- `wrapped_vmk` may be persisted server-side because it is encrypted.
- The unwrapped VMK must not be stored in localStorage, sessionStorage, IndexedDB, cookies, or URL parameters.
- The VMK may exist in browser memory only for the duration required by an active vault session.
- Logout must clear in-memory cryptographic state.
- A browser refresh requires the owner to unlock the vault again.
- Changing the vault passphrase re-wraps the same VMK; it does not regenerate the VMK.
- Losing the vault passphrase does not imply login-account recovery can recover the VMK.
- Losing sufficient Shamir shares may permanently prevent beneficiary recovery.
