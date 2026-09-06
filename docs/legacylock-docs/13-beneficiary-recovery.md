# LegacyLock — Beneficiary Recovery

## Recovery Model

MVP uses a 2-of-3 Shamir policy.

```text
VMK
 │
 ├── Share 1 → Beneficiary A
 ├── Share 2 → Beneficiary B
 └── Share 3 → Beneficiary C

Any 2 shares → VMK
```

## Share Generation

Performed entirely in the owner browser.

The server does not generate or reconstruct shares.

## Share Assignment

The backend may store:

```text
beneficiary_id
share_index
```

It does not store raw share values.

## Share Distribution

The owner distributes shares outside LegacyLock.

Examples:

- in-person handoff
- secure messaging
- physical storage
- password manager
- printed recovery card

LegacyLock does not send shares by email/SMS.

## Beneficiary Lifecycle

```text
Created
 ↓
Invitation issued
 ↓
Invitation used
 ↓
Access session
 ↓
Recovery
```

Removal revokes the beneficiary's platform relationship/invitation, but MVP does not pretend that a previously copied Shamir share has been cryptographically revoked.

## Invitation Lifecycle

```text
Generated
 ↓
Delivered
 ↓
Used
 ↓
Revoked / expired
```

An owner can reissue an invitation for the same share index without changing the vault key.

## Access

1. Beneficiary follows invitation.
2. Server validates invitation.
3. Short-lived beneficiary session is established.
4. Server verifies the vault is TRIGGERED.
5. Beneficiary enters shares in browser.
6. Valid shares are processed locally.
7. VMK is reconstructed locally.
8. Ciphertext is fetched.
9. Message keys are unwrapped locally.
10. Messages are decrypted locally.

## Share Submission

Same valid share resubmission:

```text
→ idempotent no-op
```

Invalid/different share:

```text
→ failed attempt
→ rate-limit tracking
```

This prevents accidental self-lockout while retaining brute-force protection.

## Recovery Errors

- Invalid invitation → reject
- Expired session → re-authenticate
- Vault not triggered → deny recovery
- Invalid share → failure/rate limit
- Insufficient shares → remain locked
- Successful threshold → reconstruct VMK locally

## Future Recovery Features

- Share rotation
- 3-of-5 / larger policies
- Printable/QR share cards
- Share verification
- Redundant recovery
- Beneficiary accounts
