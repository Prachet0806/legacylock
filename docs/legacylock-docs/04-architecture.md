# LegacyLock — High-Level Architecture

## Architectural Principle

> The client owns cryptographic secrets; the server owns state, metadata, orchestration, and delivery.

## System Architecture

```text
                         OWNER
                           │
                           ▼
                   ┌───────────────┐
                   │ Next.js App   │
                   └───────┬───────┘
                           │
                   ┌───────▼───────┐
                   │ Crypto Engine │
                   └───────┬───────┘
                           │ HTTPS
                           ▼
                   ┌───────────────┐
                   │ FastAPI       │
                   └───────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
       Vault          Heartbeat         Beneficiary/
       Service         Service          Recovery
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                     PostgreSQL
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                Scheduler     Notifications
```

## Beneficiary Path

```text
Beneficiary
    ↓
Access Link
    ↓
Beneficiary Session
    ↓
Triggered Status
    ↓
Shares entered locally
    ↓
Client-side reconstruction
    ↓
VMK
    ↓
Ciphertext retrieval
    ↓
Local decryption
```

## Architectural Layers

```text
Frontend
  ↓
API Router
  ↓
Service
  ↓
Repository
  ↓
Database
```

The crypto engine is a separate client-side dependency and does not depend on the backend.

## MVP Deployment

- One Next.js deployment
- One FastAPI deployment
- One PostgreSQL instance
- One basic scheduler
- Optional SendGrid/Twilio providers
- HTTPS
- `/health`

No microservices are required for MVP.
