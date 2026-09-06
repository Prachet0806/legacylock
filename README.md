# LegacyLock — Zero-Knowledge Digital Legacy Vault

LegacyLock is a **security-first web application** that allows users to securely store sensitive messages and ensure they are released only under predefined conditions (e.g., prolonged inactivity). The system is designed around **zero-knowledge principles** — the server and database can never read user data.

---

## Key Features

- **Client-side encryption (AES-256-GCM)** — All messages are encrypted in the browser before being sent to the backend.
- **Zero-knowledge backend** — The server stores only encrypted blobs and never sees plaintext, passwords, VMK, MEK, or Shamir shares.
- **Per-message random salt & IV** — Every message gets a unique 16-byte salt and 12-byte IV, preventing rainbow-table attacks.
- **Shamir's Secret Sharing (2-of-3)** — Vault master key split into shares distributed to beneficiaries.
- **Beneficiary management** — Add/remove beneficiaries, send invitations, assign key shares.
- **Access request flow** — Beneficiaries request access, owner approves/denies, auto-approve on trigger.
- **Heartbeat dead-man switch** — Configurable check-in interval and grace period to auto-trigger vault release.
- **Escalating notifications** — Grace period warnings (Day 0, Day 3, Day N-1) sent to beneficiaries.
- **Owner authentication (Argon2id + RS256 JWT)** — Secure login with rotating refresh tokens in HttpOnly cookies.
- **PostgreSQL database** — Production-ready persistent storage.

---

## Architecture

```
Browser (Next.js 16 + Tailwind + Web Crypto API)
  ├─ Argon2id password hashing for login
  ├─ PBKDF2-SHA256 (100K iterations) for vault passphrase
  ├─ AES-256-GCM for message encryption (per-message MEK)
  ├─ AES-KW for VMK wrapping
  ├─ Shamir GF(256) 2-of-3 for key splitting
  ├─ RSA-256 JWT with HttpOnly cookies for auth
  └─ In-memory VMK session (cleared on tab close)

Backend (FastAPI + SQLAlchemy + PostgreSQL)
  ├─ Argon2id password hashing
  ├─ RS256 JWT (15min access / 30day rotating refresh)
  ├─ HttpOnly cookie auth
  ├─ Beneficiary CRUD + invitation flow
  ├─ Access request workflow (request → approve → auto-approve on trigger)
  ├─ Heartbeat checker (active → grace → triggered)
  ├─ Shamir share generation & assignment
  └─ Audit logging

Database (PostgreSQL)
  ├─ users, vaults, messages, refresh_tokens
  ├─ beneficiaries, access_requests
  ├─ heartbeat_config, vault_status
  ├─ audit_events, notification_logs
  └─ Alembic migrations
```

---

## Project Structure

```
legacylock/
├── frontend/                  # Next.js 16 app (App Router)
│   ├── app/
│   │   ├── layout.tsx         # Root layout + sidebar + VaultProvider
│   │   ├── page.tsx           # Dashboard
│   │   ├── vault/
│   │   │   ├── page.tsx       # Vault (unlock, encrypt/decrypt messages)
│   │   │   └── setup/page.tsx # Vault setup (passphrase + shares)
│   │   ├── recovery/
│   │   │   ├── shares/page.tsx  # Recovery via Shamir shares
│   │   │   └── vault/page.tsx   # Recovery vault unlock + decrypt
│   │   ├── beneficiaries/page.tsx
│   │   ├── access/page.tsx      # Invitation accept + access request + share submit
│   │   ├── heartbeat/page.tsx
│   │   ├── trigger/page.tsx     # Vault trigger + status
│   │   ├── settings/page.tsx
│   │   └── globals.css        # Design tokens (Tailwind)
│   ├── components/            # Sidebar, Card, Button, Icons, VaultContext
│   ├── lib/
│   │   ├── api.ts             # Authenticated API client
│   │   ├── crypto/
│   │   │   ├── index.ts       # Web Crypto API (PBKDF2, AES-GCM, AES-KW, Shamir)
│   │   │   └── session.ts     # In-memory VMK session manager
│   │   └── crypto.ts          # Legacy (deprecated)
│   ├── .env.local
│   └── package.json
│
├── backend/                   # FastAPI app
│   ├── main.py                # App setup + lifespan (heartbeat loop) + router includes
│   ├── config.py              # Pydantic settings
│   ├── db.py                  # SQLAlchemy engine/session
│   ├── deps.py                # Auth dependencies (owner/beneficiary)
│   ├── models/                # SQLAlchemy models
│   ├── routers/
│   │   ├── access.py          # Invitation accept + access request + share submit
│   │   ├── auth.py            # Login/logout/refresh/me
│   │   ├── beneficiaries.py   # Beneficiary CRUD + invite
│   │   ├── health.py          # Health check
│   │   ├── heartbeat.py       # Heartbeat config + check-in
│   │   ├── shares.py          # Shamir share generation/reconstruction
│   │   ├── stats.py           # Dashboard stats
│   │   ├── trigger.py         # Vault trigger/reset
│   │   └── vault.py           # Message CRUD + crypto material
│   ├── services/
│   │   ├── auth.py            # Argon2id, JWT, session mgmt
│   │   ├── heartbeat_checker.py  # Background heartbeat evaluation
│   │   ├── notifications.py   # SendGrid email + Twilio SMS
│   │   └── shamir.py          # Shamir GF(256) implementation
│   ├── alembic/               # Database migrations
│   ├── tests/                 # Pytest suite (105 tests passing)
│   ├── requirements.txt
│   └── pyproject.toml
│
├── docker-compose.yml         # PostgreSQL + pgAdmin
└── README.md
```

---

## Cryptography Details

| Parameter | Value |
|-----------|-------|
| Symmetric Algorithm | AES-256-GCM |
| Key Derivation (Vault) | PBKDF2-SHA256 (100,000 iterations) |
| Key Derivation (Login) | Argon2id |
| Salt (per message) | Random 16 bytes |
| IV (per message) | Random 12 bytes |
| VMK Wrapping | AES-KW |
| Key Splitting | Shamir GF(256) 2-of-3 |
| JWT Algorithm | RS256 |
| Access Token TTL | 15 minutes |
| Refresh Token TTL | 30 days (rotating) |

**Blob layout (per message):** `version || iv || ciphertext || wrapped_MEK`, all base64-encoded.

---

## API Endpoints

### Authentication
| Route | Method | Purpose |
|-------|--------|---------|
| `/auth/login` | POST | Login (sets HttpOnly cookies) |
| `/auth/logout` | POST | Logout (clears cookies) |
| `/auth/refresh` | POST | Rotate access token |
| `/auth/me` | GET | Current user info |

### Vault
| Route | Method | Purpose |
|-------|--------|---------|
| `/vault/setup` | POST | Initialize vault (crypto material) |
| `/vault/crypto-material` | GET | Get wrapped VMK + KDF params |
| `/vault/crypto-material` | PUT | Save wrapped VMK (setup/passphrase change) |
| `/vault/messages` | POST | Save encrypted message |
| `/vault/messages` | GET | List messages |
| `/vault/messages/{id}` | GET | Get message |
| `/vault/messages/{id}` | PUT | Update message |
| `/vault/messages/{id}` | DELETE | Delete message |
| `/vault/messages` | DELETE | Wipe all messages |

### Beneficiaries
| Route | Method | Purpose |
|-------|--------|---------|
| `/beneficiaries` | POST | Add beneficiary |
| `/beneficiaries` | GET | List beneficiaries |
| `/beneficiaries/{id}` | PUT | Update beneficiary |
| `/beneficiaries/{id}` | DELETE | Remove beneficiary |
| `/beneficiaries/{id}/invite` | POST | Send invitation email |

### Access (Beneficiary)
| Route | Method | Purpose |
|-------|--------|---------|
| `/access/invite/{hash}/status` | GET | Check invitation |
| `/access/invite/{hash}/accept` | POST | Accept invitation |
| `/access/status` | GET | Beneficiary access status |
| `/access/request` | POST | Request vault access |
| `/access/requests` | GET | List own requests |
| `/access/share` | POST | Submit Shamir share |

### Access (Owner)
| Route | Method | Purpose |
|-------|--------|---------|
| `/access/requests` | GET | List all requests |
| `/access/requests/{id}/approve` | POST | Approve/deny request |
| `/access/generate-shares` | POST | Generate shares for all accepted beneficiaries |
| `/access/shares` | GET | List share assignments |

### Heartbeat
| Route | Method | Purpose |
|-------|--------|---------|
| `/heartbeat` | GET | Get config |
| `/heartbeat` | PUT | Save config |
| `/heartbeat/checkin` | POST | Record check-in |

### Trigger
| Route | Method | Purpose |
|-------|--------|---------|
| `/vault/status` | GET | Vault status + share config |
| `/vault/trigger` | POST | Manually trigger vault |
| `/vault/reset-status` | POST | Reset to active (dev) |

### Shares
| Route | Method | Purpose |
|-------|--------|---------|
| `/vault/shares/generate` | POST | Generate shares for beneficiaries |
| `/vault/shares` | GET | List share assignments |
| `/vault/shares/reconstruct` | POST | Reconstruct key from shares (public) |

### Stats
| Route | Method | Purpose |
|-------|--------|---------|
| `/stats` | GET | Dashboard statistics |

All routes require valid JWT in Authorization header or HttpOnly cookie.

---

## Local Development

### Prerequisites
- Docker Desktop (for PostgreSQL)
- Node.js 18+ / Python 3.11+

### Backend
```bash
cd backend
# Start PostgreSQL
docker compose up -d postgres

# Create venv & install
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start server
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
# Edit .env.local to set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

### Run Tests
```bash
# Backend
cd backend
venv\Scripts\python -m pytest tests/ -v

# Frontend
cd frontend
npm run typecheck
npm run build
# E2E (requires backend + dev server running)
npm run test:e2e
```

---

## Project Status

### ✅ Completed (Phase 1-3)

**Phase 1: Core Zero-Knowledge Vault**
- Argon2id login + RS256 JWT with rotating refresh tokens
- Vault setup (passphrase → PBKDF2 → wrap VMK → Shamir shares)
- Vault unlock (passphrase → unwrap VMK → in-memory session)
- Recovery flow (shares entry → reconstruct VMK → decrypt messages)
- Message CRUD (MEK per message, wrapped with VMK)
- Web Crypto API implementation (PBKDF2, AES-GCM, AES-KW, Shamir GF(256))
- In-memory VMK session (cleared on tab close/unload)

**Phase 2: Beneficiary & Access Flow**
- Beneficiary CRUD with invitation email flow
- Access request workflow (request → approve/deny)
- Auto-approve pending requests on vault trigger
- Share generation for accepted beneficiaries
- Share submission + key reconstruction

**Phase 3: Heartbeat / Dead Man's Switch**
- Heartbeat config (interval + grace period)
- Check-in endpoint + background checker
- State machine: active → grace → triggered
- Escalating notifications during grace period
- Auto-approve access requests on trigger
- Trigger notifications to beneficiaries

**Infrastructure**
- PostgreSQL with Alembic migrations
- Docker Compose for local dev
- 105 backend tests passing
- Frontend TypeScript build passing
- E2E test infrastructure (Playwright)

### 🔜 Planned (Phase 4+)
- SendGrid/Twilio integration for real notifications
- Background job runner (Celery + Redis) for production heartbeat checker
- Rate limiting on auth endpoints
- Full audit logging on all mutations
- Multi-vault support per user
- Beneficiary portal (dedicated UI for beneficiaries)
- Legal document templates
- Deployment configs (Docker, Kubernetes, CI/CD)

---

## Explicit Limitations (By Design)

- No password reset or recovery for owner or beneficiaries
- No legal enforcement (not a legal will)
- No large media files (text/markdown only)
- No server-side encryption (zero-knowledge by design)
- Single-vault per owner in current schema
- In-process heartbeat checker (needs Celery for production)

---

## Disclaimer

LegacyLock is a **technical proof-of-concept**.
It does **not** replace legal estate planning tools and should not be used as a legal will.