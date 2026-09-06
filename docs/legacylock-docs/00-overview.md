# LegacyLock

LegacyLock is a zero-knowledge digital legacy vault designed to store sensitive information and release it to designated beneficiaries after a configurable period of owner inactivity.

## Core Principle

The browser owns cryptographic secrets. The backend stores ciphertext, metadata, workflow state, and delivery status, but never receives plaintext vault content, the owner's vault password, the unencrypted Vault Master Key (VMK), or raw Shamir shares.

## Core Lifecycle

```text
Create → Encrypt → Store → Check In → Inactivity → Grace → Trigger → Recover → Decrypt
```

## MVP

The MVP proves the complete lifecycle for one owner and one vault:

- Client-side AES-256-GCM encryption
- Random per-message encryption keys
- Vault Master Key (VMK)
- Shamir 2-of-3 recovery
- Encrypted message CRUD
- Owner authentication
- Beneficiary management
- Heartbeat and grace-period state machine
- Automatic and manual trigger
- Beneficiary access and local recovery
- Mock/optional notifications
- PostgreSQL persistence
- Basic audit events

## Documentation Map

| Document | Purpose |
|---|---|
| `01-product-scope.md` | Product boundary and non-goals |
| `02-mvp-definition.md` | Concrete MVP acceptance criteria |
| `03-product-roadmap.md` | MVP-to-finished-product progression |
| `04-architecture.md` | High-level system architecture |
| `05-component-architecture.md` | Component responsibilities and dependencies |
| `06-trust-and-security.md` | Trust boundaries and security model |
| `07-cryptographic-design.md` | Key hierarchy and crypto formats |
| `08-data-model.md` | Entities and relationships |
| `09-api-design.md` | API surface and contracts |
| `10-system-flows.md` | End-to-end sequence flows |
| `11-authentication-and-access.md` | Owner/beneficiary sessions |
| `12-heartbeat-and-trigger.md` | Dead-man's-switch design |
| `13-beneficiary-recovery.md` | Recovery and share lifecycle |
| `14-threat-model.md` | Threats and mitigations |
| `15-security-requirements.md` | Security invariants |
| `16-development-plan.md` | Execution strategy |
| `17-phase-specifications.md` | Detailed phase gates |
| `18-architecture-decisions.md` | Architecture decision record |
