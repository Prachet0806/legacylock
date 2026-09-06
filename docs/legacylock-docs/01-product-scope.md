# LegacyLock — Product Scope

## Product Statement

LegacyLock is a zero-knowledge digital legacy vault that lets an owner securely store sensitive text information and make it recoverable by designated beneficiaries after a configurable period of inactivity.

## Target Actors

### Owner

Creates and manages the vault, messages, beneficiaries, heartbeat, and recovery configuration.

### Beneficiary

Does not need a full LegacyLock account in the MVP. A beneficiary uses an invitation credential and independently held recovery share(s) to access a triggered vault.

## In Scope

- Encrypted text messages
- Message CRUD and vault wipe
- Owner authentication
- Client-side encryption
- VMK/MEK key hierarchy
- Shamir threshold recovery
- 2-of-3 recovery policy in MVP
- Beneficiary management
- Out-of-band share distribution
- Heartbeat configuration
- Manual check-in
- ACTIVE → GRACE → TRIGGERED state machine
- Automatic trigger
- Manual trigger with re-authentication
- Notifications
- Access sessions
- Basic audit events
- PostgreSQL persistence
- Basic deployment/health checks

## Explicit MVP Non-Goals

- Multi-tenant production platform
- Multiple vaults per user
- Legal-will status
- Death verification
- Large file attachments
- Billing/subscriptions
- Blockchain/decentralization
- Platform-independent recovery
- Recovery of lost vault cryptographic material
- Server-mediated Shamir share delivery
- AI processing of vault contents

## Product Principles

1. Zero-knowledge guarantees take priority over convenience.
2. Cryptographic secrets remain client-side.
3. Beneficiary access must not require a traditional platform account in the MVP.
4. The server orchestrates state; it does not perform vault decryption.
5. Every irreversible workflow must be explicit and idempotent.
6. Scope should expand only when the previous phase is demonstrably stable.
