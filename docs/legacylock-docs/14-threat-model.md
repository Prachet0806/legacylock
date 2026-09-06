# LegacyLock — Threat Model

## Method

For each threat:

```text
Threat → Attack → Impact → Mitigation → Residual Risk
```

## T01 — Database Compromise

**Attack:** Attacker obtains PostgreSQL contents.

**Impact:** Ciphertext and metadata exposed.

**Mitigation:**
- Client-side encryption
- VMK never stored in plaintext
- MEKs wrapped
- Password never stored as vault key

**Residual risk:** Metadata such as labels may be visible.

## T02 — Backend Compromise

**Attack:** Attacker controls API server.

**Impact:** Can manipulate state/data and observe API traffic available to server.

**Mitigation:**
- Zero-knowledge content architecture
- TLS
- Server never receives plaintext/VMK
- Authorization
- Audit events

**Residual risk:** A malicious server can tamper with ciphertext or workflow state.

## T03 — Invitation Leakage

**Attack:** Beneficiary invitation is leaked.

**Impact:** Attacker can establish a beneficiary session if the invitation remains valid.

**Mitigation:**
- High-entropy credential
- Short-lived sessions
- Revocation
- Access requires recovery shares for actual decryption

**Residual risk:** Invitation is still sensitive.

## T04 — Share Leakage

**Attack:** Attacker obtains one or more Shamir shares.

**Impact:** Below-threshold shares should not reconstruct VMK.

**Mitigation:** 2-of-3 threshold.

**Residual risk:** Obtaining threshold shares enables recovery.

## T05 — Session Theft

**Attack:** Owner or beneficiary session is stolen.

**Impact:** Unauthorized operations within session capability.

**Mitigation:**
- Secure cookies
- Short beneficiary sessions
- Session revocation
- Server-side authorization

## T06 — Share Brute Force

**Attack:** Repeated invalid share submissions.

**Impact:** Attempt to discover valid recovery material.

**Mitigation:**
- Rate limiting
- Attempt tracking
- High-entropy share format

## T07 — Trigger Replay

**Attack:** Repeated trigger requests.

**Impact:** Duplicate trigger actions.

**Mitigation:** Atomic versioned transition and idempotency.

## T08 — Logging Leakage

**Attack:** Sensitive request body captured by logs.

**Impact:** Secrets or ciphertext leaked.

**Mitigation:**
- Redacted sensitive fields
- Exclude request bodies on sensitive endpoints
- Separate operational/audit logging

## T09 — Unauthorized Owner Operation

**Attack:** Beneficiary attempts owner endpoint.

**Impact:** Vault manipulation.

**Mitigation:** Distinct session types and server-side capabilities.

## T10 — Database Loss

**Attack:** Persistent store is destroyed.

**Impact:** Ciphertext may become unavailable even if keys exist.

**Mitigation:** Production backups and restore testing.

**MVP residual risk:** Basic backup posture.

## T11 — Malicious Browser/Client

**Attack:** User runs modified frontend or an attacker executes JavaScript in the application origin.

**Impact:** VMK, vault passphrase, plaintext, or MEKs may be exposed while present in browser memory.

**Mitigation:** Strong CSP, dependency hygiene, XSS prevention, no persistent unwrapped VMK, and minimal secret lifetime.

**Residual risk:** A fully compromised client/browser is outside the server-side zero-knowledge guarantee.

## T12 — False Trigger

**Attack:** Scheduler incorrectly triggers.

**Impact:** Premature beneficiary release.

**Mitigation:**
- Explicit state machine
- Atomic transitions
- Audit trail
- Grace period
- Manual reconfiguration

**Residual risk:** Scheduler remains an MVP single-instance component.
