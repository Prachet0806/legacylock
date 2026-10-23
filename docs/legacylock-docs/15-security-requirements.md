# LegacyLock — Security Requirements

## Security Invariants

### INV-01 — Plaintext Isolation

Plaintext vault content never crosses the client/server boundary.

### INV-02 — Password Isolation

The owner's vault password never reaches the backend.

### INV-03 — VMK Isolation

The unencrypted VMK never reaches the backend.

### INV-04 — Client Reconstruction

Shamir reconstruction occurs exclusively on the client.

### INV-05 — Share Isolation

LegacyLock never transmits raw Shamir shares on behalf of the owner.

### INV-06 — Server Knowledge Limitation

The backend must not possess sufficient unrestricted recovery material to independently reconstruct the VMK.

### INV-07 — Session Separation

Owner and beneficiary sessions are distinct.

### INV-08 — Server Authorization

Every protected operation is authorized server-side.

### INV-09 — Beneficiary Session Expiry

Beneficiary sessions are short-lived and expire automatically.

### INV-10 — Trigger Idempotency

Every path into TRIGGERED is idempotent.

### INV-11 — Trigger Authority

Only TriggerService performs release-state transitions.

### INV-12 — Access Authorization

Beneficiary status/access information requires a valid beneficiary session.

### INV-13 — Sensitive Logging Exclusion

Passwords, plaintext, VMK, MEK, raw shares, and sensitive request bodies are not logged.

### INV-14 — Crypto Versioning

Encrypted objects identify their cryptographic format.

### INV-15 — Destructive Operation Protection

Wipe and manual trigger require authenticated owner authorization and explicit confirmation/re-authentication.

### INV-16 — Development Endpoint Isolation

Development-only endpoints cannot be available in production.

### INV-17 — Authentication Recovery Separation

Login-password recovery does not recover vault cryptographic material.

### INV-18 — Independent Lifecycles

Invitation credentials and Shamir shares have independent lifecycles.

### INV-19 — [SUPERSEDED] Local Reconstruction, No Share Submission

The server never receives shares. `POST /access/share` is gone (410);
reconstruction is client-side exact-k with generation binding.

### INV-20 — Recovery Abuse Rate Limiting

Session creation, status, and message retrieval are strictly rate-limited
server-side; failed decrypts add a best-effort client-side lockout (5/15min).
The lockout is not authoritative — fewer than k valid shares is the real control.

## Testing Mapping

Every invariant should eventually map to at least one automated or manual security test.

### INV-21 — VMK At-Rest Protection

The VMK must never be persisted in unwrapped form. Persistent VMK material must be wrapped client-side using a KEK derived from the vault passphrase.

### INV-22 — VMK Session Lifetime

The unwrapped VMK may exist only in client memory during an active unlocked vault session and must be cleared on logout or equivalent session termination.

### INV-23 — Basic Client Content Security

Phase 4 MUST establish a baseline Content Security Policy and secure browser configuration appropriate to protecting in-memory cryptographic material.

## INV-29 — Metadata-Only Coverage Intelligence

The Coverage Intelligence Engine MUST operate exclusively on non-sensitive vault metadata, including `MessageCategory`, controlled coverage tags, labels, beneficiary configuration, and user-declared applicability. It MUST NOT access plaintext, ciphertext, VMK, MEK, vault passphrase, KEK, Shamir shares, or other cryptographic material.

## INV-30 — Deterministic Coverage Authority

Coverage status and Legacy Readiness scores MUST be produced by deterministic rules. Any future AI MAY explain, summarize, or prioritize these results but MUST NOT be authoritative for coverage, security, authorization, or vault state.

### INV-25 — Single-Writer Recovery Ceremony

Recovery policy (k/n/generation) changes only through draft ceremony finalization at an expected material revision. PUT /vault/crypto-material rewraps initialized material only and rejects policy fields. Every generation mutation uses a fresh ceremony; reuse returns 409. Initial material and policy finalize together.

### INV-26 — Beneficiary Session Revocation

Owner and beneficiary JWTs carry a server-side independently revocable AuthSession family ID and deployment auth epoch. Contact replacement/deletion revokes beneficiary families/challenges and clears acceptance. Logout revokes the calling family immediately. Refresh credentials rotate once; deliberate replay revokes that family, while healthy concurrency does not mass-revoke other devices. Only accepted current contacts authenticate.

### INV-27 — Durable Notification Delivery

Security-critical mutations commit one business event and unique recipient/channel delivery intent. Leased jobs move READY/RETRY_WAIT → CLAIMED → ACCEPTED, RETRY_WAIT or DEAD; obsolete work is CANCELLED. Claims and actual provider-call timestamps are separate evidence. Provider acceptance is not inbox delivery. Protected credential payloads expire and are erased; raw links never enter logs.

### INV-28 — Correlated Audit Trail

Security-sensitive audit events carry request_id + IP for HTTP↔audit↔log traceability. Test/verification endpoints exist in the test environment only.

## Threat Model (Phase B baseline)

- **Server/DB compromise:** stored content is ciphertext and wrapped keys, with server-visible account, label, category, assignment and timing metadata. JWT key theft can forge sessions but alone does not decrypt vault content. A compromised server able to deliver modified application JavaScript can attack an unlocking browser.
- **Frontend/XSS compromise:** full vault compromise is possible while the browser holds secrets. Dynamic nonce CSP, redaction, epoch-bound key lifetime and dependency controls reduce exposure; they do not make compromised code safe.
- **Beneficiary compromise:** ciphertext fetch requires TRIGGERED + accepted status + valid session; shares reconstruct only client-side with exact-k + generation binding.
- **Token theft:** short-lived access is family/epoch revocable; refresh is hash-stored and single-use for both roles. Fresh beneficiary identity relies on mailbox control, independently of separately held shares.
- **Notification provider compromise:** recipients, notification metadata and authentication links are exposed to the provider; encrypted vault content, passphrases and recovery shares are not sent in notices.
- **Two secrets:** the login password authenticates; the vault passphrase decrypts. Password reset (if ever added) must not imply vault recovery.
