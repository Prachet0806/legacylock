# LegacyLock — MVP Definition

## Objective

Prove the complete LegacyLock mechanic end-to-end:

> Client-side encryption → threshold recovery setup → inactivity monitoring → release → beneficiary-side local decryption.

## MVP Architecture

```text
Owner Browser
  ├── Web UI
  └── Crypto Engine
          │
        HTTPS
          │
          ▼
      FastAPI
          │
     PostgreSQL
```

Beneficiary recovery uses the same client crypto engine but a separate short-lived beneficiary session.

## Required Capabilities

### Vault

- Create encrypted message
- List messages
- Read message
- Update message
- Delete message
- Wipe all messages

### Cryptography

- Random VMK
- Random MEK per message
- AES-256-GCM
- PBKDF2-SHA256 with documented fixed parameters for the MVP
- Versioned crypto format
- Shamir 2-of-3
- Client-side reconstruction

### Heartbeat

- Configurable check-in interval
- Grace period
- Manual check-in
- ACTIVE state
- GRACE state
- TRIGGERED state

### Trigger

- Automatic trigger
- Manual trigger
- Re-authentication
- Confirmation
- Atomic/idempotent state transition

### Beneficiary

- Add beneficiary
- Remove beneficiary
- Invitation credential
- Share-index assignment
- Access page
- Short-lived beneficiary session

### Recovery

- Submit shares
- Same valid share submission is idempotent
- Invalid submissions are rate-limited
- VMK reconstruction happens only in the browser
- Messages decrypt locally

## Share Distribution Rule

LegacyLock never transmits raw Shamir shares on behalf of the owner.

The owner receives/displays the generated shares and distributes them through a secure channel outside LegacyLock.

## MVP Success Scenario

A single owner can:

1. Create at least three encrypted messages.
2. Configure three beneficiaries.
3. Establish a 2-of-3 recovery policy.
4. Securely distribute shares out-of-band.
5. Configure a heartbeat.
6. Simulate inactivity.
7. Observe ACTIVE → GRACE → TRIGGERED.
8. Allow a beneficiary with two valid shares to reconstruct the VMK locally.
9. Decrypt a message locally.
10. Verify the backend never possessed plaintext or the unencrypted VMK.

## Definition of Done

- [x] Plaintext never sent to backend (`zero_knowledge_network_boundary.spec.ts` boundary assertion)
- [x] Owner vault password never sent to backend (same assertion; login password only to auth endpoints)
- [x] VMK never sent to backend (same assertion; wrapped VMK only)
- [x] Raw shares never sent by LegacyLock (same assertion; `LLS1-` shares local-only)
- [x] Three encrypted messages work (golden path creates + recovers 3)
- [x] Message CRUD works (backend `test_vault.py` + E2E create/read/decrypt)
- [x] 2-of-3 recovery works (golden path, default ceremony)
- [x] Heartbeat works (`test_heartbeat*.py`, heartbeat UI schedule save/check-in)
- [x] Grace period works (`heartbeat_auto_trigger.spec.ts`: ACTIVE → GRACE, check-in cancels)
- [x] Automatic trigger works (`heartbeat_auto_trigger.spec.ts` + `test_heartbeat_run_check.py`, reason=inactivity)
- [x] Manual trigger works (golden path `/heartbeat` danger zone)
- [x] Trigger is idempotent (`test_trigger.py` concurrency + auto re-run no-op)
- [x] Beneficiary access works (invite accept → TRIGGERED-gated status/messages)
- [x] Local reconstruction works (exact-k + generation binding, `crypto.spec.ts` 14/14)
- [x] Local decryption works (both E2E specs decrypt to matching plaintext)
- [x] Sensitive request bodies are not logged (`09-api-design.md` allowlist + boundary assertions)
- [x] Production build and backend tests pass (`next build`, 155 pytest, 28 Playwright)

## Owner Unlock Acceptance Criteria

- Owner can close/refresh the browser and later unlock the existing vault.
- The existing VMK remains stable across unlocks.
- The backend persists only the wrapped VMK.
- A login-password reset does not reveal or regenerate the VMK.

## MVP Coverage Intelligence

The MVP includes a rules-based Coverage Intelligence Engine providing controlled message categories, controlled coverage tags, owner-declared applicability, deterministic coverage scoring, and missing-area recommendations. An LLM is not required.

Each message has exactly one primary category; users are encouraged to split unrelated topics into separate messages.
