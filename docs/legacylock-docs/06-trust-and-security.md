# LegacyLock — Trust Boundaries & Security Architecture

## Trust Model

```text
┌─────────────────────────────────────────────┐
│              TRUSTED CLIENT                 │
│                                             │
│ Plaintext                                    │
│ Vault password                               │
│ VMK                                          │
│ MEKs                                         │
│ Shamir shares                                │
│ Reconstruction                               │
└──────────────────────┬──────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────┐
│              UNTRUSTED SERVER               │
│                                             │
│ Ciphertext                                   │
│ Wrapped MEKs                                 │
│ Metadata                                     │
│ Heartbeat state                              │
│ Beneficiary metadata                         │
│ Recovery policy                              │
│ Audit events                                 │
│                                             │
│ NEVER: plaintext / VMK / password / shares  │
└──────────────────────┬──────────────────────┘
                       ▼
                  PostgreSQL
```

## Server May Know

- Message labels
- Ciphertext
- Wrapped message keys
- Crypto metadata
- Beneficiary metadata
- Heartbeat configuration/state
- Vault status
- Notification status
- Audit metadata
- Access attempt metadata

## Server Must Not Know

- Plaintext message content
- Owner vault password
- Unencrypted VMK
- Unencrypted MEKs
- Raw Shamir shares
- Reconstructed VMK

## Share Distribution

Shares are generated client-side and distributed by the owner outside LegacyLock.

LegacyLock may store:

```text
beneficiary_id
share_index
```

but not the raw share value.

## Session Isolation

Owner and beneficiary sessions use different credentials and scopes. Server-side authorization is authoritative.

## Logging

Operational logging and security audit events are separate.

Sensitive request/response bodies must be excluded or redacted.

Never log:

- passwords
- plaintext
- VMK
- MEK
- raw shares
- sensitive request bodies

## MVP Accepted Risks

- Single-instance scheduler
- Basic authentication
- Manual share distribution
- No share rotation
- Text-only content
- Single-owner UX

These are deliberate scope decisions, not hidden limitations.
