# LegacyLock — Phase Specifications

## Phase 1 — Core Zero-Knowledge Vault

### Objective

Prove secure client-side encryption and encrypted storage.

### Scope

- Owner authentication
- Vault UI
- Message CRUD
- VMK/MEK model
- Client-side VMK generation
- Client-side KEK derivation
- Client-side VMK wrapping/unwrapping
- Wrapped VMK persistence
- AES-256-GCM
- KDF
- PostgreSQL
- Basic authorization

### Excluded

- Heartbeat
- Automatic trigger
- Beneficiary recovery
- Files
- Multi-tenancy

### Exit Criteria

Encrypted messages can be created, stored, retrieved, and decrypted locally.

---

## Phase 2 — Heartbeat & Release

### Objective

Implement the dead-man's-switch state machine.

### Scope

- Check-in
- Deadline
- Grace period
- ACTIVE/GRACE/TRIGGERED
- Automatic trigger
- Manual trigger
- Re-authentication
- Atomic idempotency
- Scheduler
- Basic notifications

### Excluded

- Distributed scheduler
- Multi-region failover
- Advanced recovery

### Exit Criteria

ACTIVE → GRACE → TRIGGERED works and repeated triggers cannot duplicate the transition.

---

## Phase 3 — Beneficiary & Recovery

### Objective

Complete the portfolio MVP.

### Scope

- Beneficiary CRUD
- Invitation credential
- Beneficiary session
- Share assignment
- Out-of-band share distribution
- Access page
- 2-of-3 Shamir
- Local reconstruction
- Local decryption
- Rate limiting
- Recovery audit events

### Exit Criteria

Two valid shares reconstruct the VMK locally and allow message decryption after trigger.

### Portfolio Gate

Phases 1–3 are the official portfolio MVP.

---

## Phase 4 — Production Security Foundation

### Objective

Remove major security weaknesses.

### Scope

- Strong password hashing
- Session hardening
- Authorization review
- Invitation revocation
- Rate limiting
- Stable beneficiary/invitation attempt counters
- Sensitive logging controls
- Baseline Content Security Policy
- XSS/dependency hygiene review
- Threat-model review
- Crypto test vectors

### Excluded

- Multi-tenancy
- Billing
- File storage

### Exit Criteria

No known critical authentication, authorization, secret-leakage, or replay weakness remains.

---

## Phase 5 — Production Reliability

### Objective

Make the existing system dependable.

### Scope

- Scheduler failure recovery
- Notification retries
- Delivery status
- Database backups
- Restore testing
- Monitoring
- Structured logs
- Error tracking

### Excluded

- Kubernetes
- Microservices
- Kafka
- Multi-region architecture unless justified

### Exit Criteria

Restart/failure scenarios converge to the correct state without duplicate triggers.

---

## Phase 6 — Multi-Tenant Product

### Objective

Support real users and multiple vaults.

### Scope

- User model
- Registration
- Login
- Account recovery
- Multiple vaults
- Per-vault beneficiaries
- Per-vault heartbeat
- Tenant isolation

### Exit Criteria

A user cannot access another user's vault or associated resources.

---

## Phase 7 — Rich Legacy Content

### Objective

Expand from small text to larger encrypted content.

### Scope

- Files
- Images
- PDFs
- Structured message templates
- Chunked client-side encryption
- Object storage
- Metadata references

### Excluded

- Unbounded media archives
- Server-side plaintext processing

### Exit Criteria

Large encrypted objects can be uploaded, stored, downloaded, and decrypted client-side.

---

## Phase 8 — Mature Recovery & Key Ceremony

### Objective

Make cryptographic recovery usable and maintainable.

### Scope

- Guided share ceremony
- QR/printable shares
- Share verification
- Larger threshold configurations
- Share rotation
- Beneficiary removal with cryptographic revocation
- Recovery redundancy

### Exit Criteria

Recovery configuration can change without leaving removed beneficiaries with permanent access.

---

## Phase 9 — Security & Production Posture

### Objective

Reach mature security-product posture.

### Scope

- Argon2id evaluation/migration
- Passkeys/WebAuthn
- External penetration testing
- Cryptographic review
- SAST/DAST
- Dependency scanning
- Secret scanning
- Advanced anomaly detection
- Transparency/audit UI

### Exit Criteria

External security review is completed and critical findings are resolved.
