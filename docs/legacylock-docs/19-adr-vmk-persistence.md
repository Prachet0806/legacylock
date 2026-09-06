# ADR-017 — VMK Persistence and At-Rest Wrapping

## Status

Accepted.

## Context

The Vault Master Key (VMK) is intentionally randomly generated rather than derived directly from the owner's login password. A random VMK cannot be regenerated after logout, browser refresh, crash, or restart, so the owner needs persistence without exposing the VMK to the backend.

## Decision

Persist the VMK only in **wrapped form**. A dedicated **Vault Passphrase** derives a **Key Encryption Key (KEK)** locally. The KEK wraps the VMK.

```text
Login Password ──→ Authentication only

Vault Passphrase ──→ KDF ──→ KEK ──→ Wrap/Unwrap ──→ VMK
                                                     ├─ Shamir 2-of-3
                                                     └─ Wrap MEKs
```

The backend may store:

```text
wrapped_vmk
vmk_crypto_version
vmk_kdf_algorithm
vmk_kdf_salt
vmk_kdf_parameters
```

It must never store the vault passphrase, KEK, or unwrapped VMK.

## Consequences

### Positive

- Owner can unlock the same vault across sessions.
- VMK remains independent of login-password entropy.
- Backend remains outside the vault decryption trust boundary.
- Changing the vault passphrase does not require re-encrypting messages.

### Negative

- Owner must remember a separate vault passphrase.
- Losing the vault passphrase can prevent normal owner unlock.
- Losing sufficient recovery shares can prevent beneficiary recovery.
- Browser memory must be treated as sensitive while the vault is unlocked.

## Lifecycle

### Setup

```text
Generate VMK → Shamir split → Derive KEK → Wrap VMK → Persist wrapped VMK
```

### Unlock

```text
Authenticate → Enter vault passphrase → Derive KEK → Fetch wrapped VMK → Unwrap locally
```

### Logout

Clear VMK, KEK, plaintext, and derived cryptographic state from application memory.

### Vault Passphrase Change

Unlock the VMK, derive a new KEK, and re-wrap the same VMK. Do not regenerate the VMK.

## Security Requirements

1. Unwrapped VMK is never persisted.
2. VMK is never sent to the backend.
3. KEK is never sent to the backend.
4. Vault passphrase is never sent to the backend.
5. Login-password recovery does not recover vault cryptographic material.
6. VMK is cleared on logout.
7. Crypto metadata is versioned.
8. VMK wrapping uses an authenticated encryption/key-wrapping construction appropriate for key material.

## Alternatives Rejected

### Derive VMK directly from login password

Rejected because it couples the root key to human password entropy.

### Store VMK directly in PostgreSQL

Rejected because database compromise would directly compromise the vault.

### Store VMK in localStorage

Rejected because persistent browser storage increases XSS impact.

### Keep VMK only in memory

Rejected because refresh/logout/restart would make normal owner access impossible.

## Related Decisions

- ADR-001 — VMK is the Shamir secret
- ADR-002 — MEK per message
- ADR-003 — Client-side Shamir reconstruction
- ADR-005 — Login password and vault secret are separate

## API Contract

The owner client retrieves and stores wrapped VMK material through:

```text
GET /vault/crypto-material
PUT /vault/crypto-material
```

These endpoints operate only on wrapped VMK material and non-secret crypto metadata. They never accept or return the vault passphrase, KEK, or unwrapped VMK.
