# LegacyLock — API Design

Base path: none (routers register unversioned: `/auth`, `/vault`,
`/beneficiaries`, `/heartbeat`, `/access`, `/stats`, `/health`).

> Decision: no `/api/v1` prefix for MVP. Introduce versioning only when a
> second client exists that needs a stability contract.

## Authentication

```text
POST /auth/login
POST /auth/logout
GET  /auth/me
```

## Vault Messages

```text
POST   /vault/messages
GET    /vault/messages
GET    /vault/messages/{id}
PUT    /vault/messages/{id}
DELETE /vault/messages/{id}
DELETE /vault/messages
```

`DELETE /vault/messages` is a destructive bulk operation and requires authenticated owner authorization.

## Vault Status

```text
GET  /vault/status
POST /vault/trigger
```

Manual trigger requires owner authentication and re-authentication/confirmation.

## Beneficiaries

```text
POST   /beneficiaries
GET    /beneficiaries
DELETE /beneficiaries/{id}
```

Invitation credentials and share assignments have independent lifecycles.

## Heartbeat

```text
GET  /heartbeat
PUT  /heartbeat
POST /heartbeat/checkin
```

## Recovery

```text
POST /access/session
GET  /access/status
POST /access/share                # {share_hash} only — raw shares are rejected
POST /access/share/report-mismatch
GET  /access/messages             # TRIGGERED-gated metadata list
GET  /access/messages/{id}        # TRIGGERED-gated ciphertext + wrapped MEK
GET  /vault/share-assignments     # metadata only (alias of /access/share-assignments)
```

`POST /vault/shares` was removed: shares are generated client-side, the server
only records share-index assignments (`POST /beneficiaries/{id}/assign-share`).

The API never reconstructs the VMK.

## Statistics

```text
GET /stats
```

## Health

```text
GET /health
```

## Development Reset

If retained:

```text
POST /vault/reset-status
```

It must only be registered/available in development environments.

## Authentication Rules

Every protected endpoint must identify:

- Principal
- Session type
- Vault ownership/access
- Allowed operation

## Error Semantics

| Status | Meaning |
|---|---|
| 400 | Malformed request |
| 401 | Missing/invalid authentication |
| 403 | Authenticated but unauthorized |
| 404 | Resource does not exist |
| 409 | State/conflict condition |
| 413 | Payload too large |
| 422 | Validation failure |
| 429 | Rate limited |
| 500 | Unexpected server failure |

Missing resources must use HTTP 404 rather than a 200 response containing an error object.

## Sensitive Request Logging

Do not log raw request bodies for:

- authentication
- message creation/update
- access/share submission

Use request IDs and safe metadata instead.

## Share Endpoint Naming Rule

`GET /vault/share-assignments` returns only assignment/metadata information. It MUST NOT return raw Shamir share material.

## Vault Cryptographic Material

The API exposes the **wrapped** VMK and non-secret metadata so the owner browser can unlock the vault locally.

```text
GET /vault/crypto-material
PUT /vault/crypto-material
```

### GET /vault/crypto-material

Returns:

- `wrapped_vmk`
- `vmk_crypto_version`
- `vmk_kdf_algorithm`
- `vmk_kdf_salt`
- `vmk_kdf_parameters`

It MUST NOT return:

- vault passphrase
- KEK
- unwrapped VMK

### PUT /vault/crypto-material

Used during initial vault setup and vault-passphrase changes.

The browser derives the KEK and performs VMK wrapping before sending the wrapped material.

Changing the vault passphrase replaces the wrapped VMK representation but does not replace the VMK itself.

### API Security Rule

The API must never accept a request field representing the vault passphrase, KEK, or unwrapped VMK.

## Coverage API

> Deferred: only `category`/`coverage_tags` plumbing exists on messages.
> There is no scoring engine and no `GET /vault/coverage` endpoint yet.

### GET /vault/coverage (planned)

**Authorization:** Owner session only.

Returns the deterministic Coverage Intelligence report. Numeric and `partial` results are valid because the MVP includes controlled `coverage_tags`.

```json
{
  "overall_score": 72,
  "categories": [
    {
      "category": "financial",
      "status": "partial",
      "score": 67,
      "covered": ["banking", "investments"],
      "missing": ["loans"]
    }
  ],
  "recommendations": [
    {
      "category": "insurance",
      "priority": "high",
      "reason": "No insurance-related coverage has been documented."
    }
  ]
}
```

The endpoint never returns plaintext message content or cryptographic material.
