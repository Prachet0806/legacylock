# LegacyLock — Authentication & Access

## Authentication Domains

LegacyLock has two distinct session types.

### Owner Session

Authenticated using the owner's login credential.

Capabilities:

```text
vault:read
vault:write
vault:delete
beneficiary:manage
heartbeat:manage
trigger:execute
settings:manage
```

### Beneficiary Session

Established from a valid invitation credential.

Capabilities:

```text
access:read
share:submit
```

A beneficiary session cannot perform owner operations.

## Credential Separation

```text
Login Password
     │
     ▼
Authentication
     │
     ▼
Owner Session


Vault Passphrase
     │
     ▼
Local KDF
     │
     ▼
KEK
     │
     ▼
Unwrap Wrapped VMK
     │
     ▼
VMK → Crypto Engine
```

The login password authenticates the owner account. It is not used to derive or recover the VMK.

The vault passphrase is a separate cryptographic unlock secret. It is processed only in the browser and is never sent to the backend.

## Owner Password Recovery

Account login-password recovery is permitted.

Recovery of lost vault cryptographic material is not.

Therefore:

```text
Forgot login password → recover account
Lost VMK/recovery shares → vault may be unrecoverable
```

## Beneficiary Invitation

Invitation credentials are:

- high entropy
- non-sequential
- revocable
- long-lived until revoked/used according to policy

The database stores a secure hash, not the raw credential.

## Beneficiary Session

MVP policy:

- short-lived
- approximately 30-minute lifetime
- approximately 10-minute idle timeout
- independently revocable
- distinct from owner session

Exact values are configuration, not protocol requirements.

## Session Isolation

Use distinct session cookie names/scopes for owner and beneficiary contexts.

Example:

```text
legacylock_owner_session
legacylock_access_session
```

Server-side session type validation remains authoritative.

## Access Status

Beneficiaries may not enumerate vault status anonymously.

Status is exposed only after a valid beneficiary access session is established.

## Invitation vs Share vs Session

These are separate objects:

```text
Invitation credential
        ≠
Shamir share
        ≠
Beneficiary session
        ≠
VMK
```

A lost invitation can be reissued without changing the share assignment.

A lost Shamir share requires future key/share rotation.

## Authorization

Authorization must be checked on every protected endpoint.

Never rely solely on frontend route visibility.

## Coverage Authorization

`GET /vault/coverage` is owner-only. A beneficiary session MUST NOT access owner Coverage Intelligence reports.
