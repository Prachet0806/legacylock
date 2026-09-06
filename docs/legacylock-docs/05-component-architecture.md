# LegacyLock — Component Architecture

## Components

| ID | Component | Responsibility |
|---|---|---|
| C1 | Owner Web Client | Owner UI |
| C2 | Beneficiary Web Client | Recovery UI |
| C3 | Client Crypto Engine | Encryption, keys, Shamir |
| C4 | Authentication & Session Service | Identity/session/authorization |
| C5 | Vault Service | Encrypted message lifecycle |
| C6 | Beneficiary Service | Beneficiary and invitation management |
| C7 | Recovery Service | Recovery policy and access metadata |
| C8 | Heartbeat Service | Inactivity evaluation |
| C9 | Trigger Service | Release state transitions |
| C10 | Notification Service | Email/SMS/mock delivery |
| C11 | Background Scheduler | Periodic evaluation |
| C12 | Persistence & Audit Layer | Database access and audit events |

## C1 — Owner Web Client

Owns:

- Dashboard
- Vault
- Beneficiaries
- Heartbeat
- Settings
- Login
- Confirmation UX

Does not own cryptographic primitives directly; it calls C3.

## C2 — Beneficiary Web Client

Owns:

- Access page
- Invitation/session handling
- Share input
- Recovery progress
- Local decryption display

## C3 — Client Crypto Engine

Owns:

- VMK generation
- MEK generation
- KDF
- AES-GCM
- Key wrapping/unwrapping
- Shamir split/reconstruction
- Encoding/decoding
- Crypto format versioning

## C4 — Authentication & Session Service

Owns:

- Owner authentication
- Owner session
- Beneficiary session
- Session expiry
- Session revocation
- Role/capability enforcement

## C5 — Vault Service

Owns:

- Create/read/update/delete message
- List messages
- Wipe vault messages
- Ciphertext metadata validation

Never decrypts content.

## C6 — Beneficiary Service

Owns:

- Create/remove beneficiary
- Invitation credentials
- Share-index assignment
- Invitation revocation/reissue

## C7 — Recovery Service

Owns:

- Recovery policy
- Threshold/total metadata
- Access eligibility
- Share submission tracking
- Rate-limit coordination

Does not reconstruct the VMK.

## C8 — Heartbeat Service

Owns:

- Configuration
- Check-in
- Deadline calculation
- State evaluation

## C9 — Trigger Service

Owns:

- Manual trigger
- Automatic trigger transition
- Atomic state updates
- Idempotency
- Trigger audit event

## C10 — Notification Service

Provider-independent interface:

```text
NotificationService
 ├── MockProvider
 ├── EmailProvider
 └── SMSProvider
```

Never transports raw Shamir shares.

## C11 — Scheduler

Only initiates periodic evaluation:

```text
Scheduler → HeartbeatService.evaluate()
```

It does not implement business rules.

## C12 — Persistence & Audit

Repositories provide lightweight database isolation:

```text
Service → Repository → SQLAlchemy → PostgreSQL
```

Avoid excessive abstraction in MVP.
