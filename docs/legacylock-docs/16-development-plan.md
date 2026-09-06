# LegacyLock — Development Plan

## Development Philosophy

LegacyLock uses iterative development with strict phase gates.

Each phase should produce a working increment rather than a large batch of unfinished features.

## Implementation Order

```text
Architecture
 ↓
Core Crypto
 ↓
Encrypted Vault
 ↓
Heartbeat
 ↓
Trigger
 ↓
Beneficiary Access
 ↓
Recovery
 ↓
Security Hardening
 ↓
Reliability
 ↓
Product Expansion
```

## Working Rules

1. Keep scope frozen within a phase.
2. Finish tests before starting the next phase.
3. Prefer simple architecture that preserves the security model.
4. Do not introduce infrastructure without a concrete requirement.
5. Do not move cryptographic secrets to the backend for convenience.
6. Treat security invariants as acceptance criteria.

## Development Workflow

For each feature:

```text
Design
 ↓
Implement
 ↓
Unit Test
 ↓
Integration Test
 ↓
Manual Verification
 ↓
Document
 ↓
Commit
```

## Recommended Git Strategy

Use small, meaningful commits:

```text
feat: add vault message update
fix: enforce trigger version check
security: redact access request logging
test: add beneficiary session expiry tests
docs: update recovery flow
```

## Testing Layers

### Unit

- Crypto functions
- KDF
- Shamir
- state transitions
- services

### Integration

- API + database
- authentication
- heartbeat
- trigger
- beneficiary access

### End-to-End

- Create message → retrieve → decrypt
- Trigger → beneficiary recovery → decrypt

### Security

- Unauthorized endpoint access
- cross-vault access
- invalid shares
- replayed trigger
- sensitive logging
- invitation revocation

## Definition of Done

A feature is complete only when:

- Code works
- Tests pass
- Error paths are handled
- Security invariants remain true
- UI handles loading/errors
- Documentation is updated
