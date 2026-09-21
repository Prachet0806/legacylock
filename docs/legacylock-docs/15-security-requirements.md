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

## INV-23 — Metadata-Only Coverage Intelligence

The Coverage Intelligence Engine MUST operate exclusively on non-sensitive vault metadata, including `MessageCategory`, controlled coverage tags, labels, beneficiary configuration, and user-declared applicability. It MUST NOT access plaintext, ciphertext, VMK, MEK, vault passphrase, KEK, Shamir shares, or other cryptographic material.

## INV-24 — Deterministic Coverage Authority

Coverage status and Legacy Readiness scores MUST be produced by deterministic rules. Any future AI MAY explain, summarize, or prioritize these results but MUST NOT be authoritative for coverage, security, authorization, or vault state.
