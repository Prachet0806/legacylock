# LegacyLock — System Flows

## Flow A — Create Message

```text
Owner
 ↓
Vault UI
 ↓
Crypto Engine
 ├── generate MEK
 ├── generate random IV
 ├── AES-256-GCM encrypt
 ├── wrap MEK with VMK
 └── serialize payload
 ↓
HTTPS
 ↓
Authentication
 ↓
Vault Service
 ↓
Repository
 ↓
PostgreSQL
 ↓
Audit Event
 ↓
201 Created
```

Plaintext never crosses the boundary.

## Flow I — Initial Vault Setup

```text
Owner Browser
 ↓
Generate random VMK
 ↓
Generate Shamir shares from VMK
 ↓
Derive KEK from vault passphrase
 ↓
Wrap VMK with KEK
 ↓
Persist wrapped VMK + KDF metadata
 ↓
Distribute Shamir shares out-of-band
```

The backend receives only the wrapped VMK and non-secret crypto metadata.

## Flow J — Vault Unlock

```text
Owner login
 ↓
Owner session established
 ↓
Prompt for vault passphrase
 ↓
Derive KEK locally
 ↓
GET wrapped VMK + KDF metadata
 ↓
Unwrap VMK locally
 ↓
Hold VMK in browser memory
 ↓
Fetch encrypted messages
 ↓
Decrypt locally as needed
```

The login password and vault passphrase are never sent to the backend.

## Flow K — Vault Lock / Logout

```text
Owner logout or lock
 ↓
Clear VMK from application memory
 ↓
Clear KEK from application memory
 ↓
Clear plaintext message state
 ↓
Destroy owner session
```

Persistent browser storage must not contain the unwrapped VMK or KEK.

## Flow L — Vault Passphrase Change

```text
Owner unlocks vault
 ↓
VMK available in memory
 ↓
Enter new vault passphrase
 ↓
Derive new KEK locally
 ↓
Re-wrap existing VMK
 ↓
Persist replacement wrapped VMK + KDF metadata
 ↓
Discard old KEK
```

Changing the vault passphrase does not regenerate the VMK and does not require re-encrypting messages.

## Flow B — Read Message

```text
Owner
 ↓
API
 ↓
Authentication
 ↓
Vault Service
 ↓
Ciphertext + wrapped MEK
 ↓
Browser
 ↓
Crypto Engine
 ↓
Unwrap MEK using VMK
 ↓
AES-GCM decrypt
 ↓
Plaintext
```

## Flow C — Update Message

Same trust model as creation:

```text
Plaintext → Client Crypto → Ciphertext → API → Database
```

The server replaces encrypted content and associated crypto metadata.

## Flow D — Check-in

```text
Owner
 ↓
POST /heartbeat/checkin
 ↓
Authentication
 ↓
Heartbeat Service
 ↓
Update last_checkin
 ↓
Calculate deadline
 ↓
Audit Event
```

A check-in during GRACE returns the vault to ACTIVE according to the state rules.

## Flow E — Automatic Trigger

```text
Scheduler
 ↓
HeartbeatService.evaluate()
 ↓
Eligible vault?
 ↓
TriggerService
 ↓
Atomic conditional update
 ↓
State transition
 ↓
Audit Event
 ↓
Notification Service
```

## Flow F — Manual Trigger

```text
Owner
 ↓
Re-authentication
 ↓
Confirmation
 ↓
POST /vault/trigger
 ↓
Authentication
 ↓
TriggerService
 ↓
Atomic transition
 ↓
Audit
 ↓
Notification
```

Automatic and manual triggers use the same transition mechanism.

## Flow G — Beneficiary Recovery

```text
Beneficiary
 ↓
Invitation
 ↓
Access Session
 ↓
Check triggered status
 ↓
Enter Share A
 ↓
Enter Share B
 ↓
Client-side Shamir reconstruction
 ↓
VMK
 ↓
Fetch ciphertext
 ↓
Unwrap MEK
 ↓
AES-GCM decrypt
 ↓
Plaintext
```

## Flow H — Share Setup

```text
Owner Browser
 ↓
Generate random VMK
 ↓
Shamir split VMK
 ↓
Display shares once
 ↓
Owner distributes shares out-of-band
```

Share generation and distribution are independent of VMK-at-rest wrapping.

LegacyLock stores share assignment metadata, not raw share values.

## Failure Principles

- Authentication failure → reject before business logic.
- Authorization failure → no resource disclosure.
- Database failure → safe error; no secret logging.
- Duplicate trigger → idempotent no-op.
- Duplicate valid share submission → idempotent.
- Invalid share submission → count and rate-limit.

## Flow M — Coverage Evaluation

```text
Vault metadata
     │
     ├── MessageCategory
     ├── CoverageTag[]
     └── Applicability
             │
             ▼
     Coverage Rules Registry
             │
             ▼
     Deterministic Evaluator
             │
      ┌──────┴──────┐
      ▼             ▼
 Category status  Missing areas
      │             │
      └──────┬──────┘
             ▼
      Legacy Readiness
             │
             ▼
       Coverage Report
```

The evaluator never decrypts a message.

## Flow N — First-Run Coverage Setup

```text
Owner opens Coverage Advisor
        ↓
Select APPLICABLE / NOT_APPLICABLE
        ↓
Unresolved domains remain UNKNOWN
        ↓
Only APPLICABLE domains affect readiness
```

## Flow O — Create Message With Coverage Metadata

```text
Create message
     ↓
Select exactly one MessageCategory
     ↓
Select compatible CoverageTag values
     ↓
Encrypt content locally
     ↓
Persist ciphertext + metadata
```

Unrelated topics should be split into separate messages.
