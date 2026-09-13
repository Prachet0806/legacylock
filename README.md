# LegacyLock — Zero-Knowledge Digital Legacy Vault

LegacyLock is a **security-first web application** that allows users to securely store sensitive messages and ensure they are released only under predefined conditions (e.g., prolonged inactivity). The system is designed around **zero-knowledge principles** — the server and database can never read user data.

---

## Key Features

- **Client-side encryption (AES-256-GCM)** — All messages are encrypted in the browser before being sent to the backend.
- **Zero-knowledge backend** — The server stores only encrypted blobs and never sees plaintext, passwords, VMK, MEK, or Shamir shares.
- **Per-message random IV** — Every message gets a unique 12-byte IV; each vault gets
  a unique 16-byte KDF salt, preventing rainbow-table attacks.
- **Shamir's Secret Sharing (2-of-3)** — Vault master key split client-side into shares
  distributed to beneficiaries out-of-band; any 2 reconstruct.
- **Beneficiary management** — Add/remove beneficiaries, send invitations (hash-stored,
  single-use, 7-day expiry), assign share indexes.
- **Beneficiary recovery flow** — Invitation accept → short-lived session → share-hash
  submission (idempotent, rate-limited) → ciphertext fetch after TRIGGERED → local
  reconstruct + decrypt. The backend never reconstructs the VMK.
- **Heartbeat dead-man switch** — Configurable check-in interval and grace period
  (`grace_days` must not exceed `interval_days`) to auto-trigger vault release.
- **Escalating notifications** — Grace period warnings (Day 0, Day 3 if grace > 3 days,
  final 24h with SMS when a phone is on file) sent to beneficiaries. Notifications
  are mock-logged in development; SendGrid/Twilio keys enable real delivery.
- **Owner authentication (Argon2id + RS256 JWT)** — Secure login with rotating refresh tokens in HttpOnly cookies.
- **PostgreSQL database** — Production-ready persistent storage.

---

## Architecture

```
Browser (Next.js 14 + Tailwind + Web Crypto API)
  ├─ PBKDF2-SHA256 (600K iterations) for vault passphrase
  ├─ AES-256-GCM for message encryption (per-message MEK)
  ├─ AES-KW for VMK wrapping
  ├─ Shamir GF(256) 2-of-3 for key splitting (client split + reconstruct only)
  ├─ RS256 JWT with HttpOnly cookies for auth
  └─ In-memory VMK session (cleared on tab close)

Backend (FastAPI + SQLAlchemy + PostgreSQL)
  ├─ Argon2id password hashing
  ├─ RS256 JWT (15min access / 30day rotating refresh)
  ├─ HttpOnly cookie auth
  ├─ Beneficiary CRUD + invitation flow (hash-stored, single-use)
  ├─ Share-index assignment metadata (no raw shares stored)
  ├─ Heartbeat checker (active → grace → triggered, version CAS)
  ├─ Beneficiary ciphertext fetch (TRIGGERED-gated, vault-scoped)
  └─ Audit logging (DB-persisted + stdout)

Database (PostgreSQL)
  ├─ users, vaults, messages, refresh_tokens
  ├─ beneficiaries, share_attempts
  ├─ heartbeat_config, vault_status
  ├─ audit_events, notification_logs
  └─ Alembic migrations
```

---

## Project Structure

```
legacylock/
├── frontend/                  # Next.js 14 app (App Router, Tailwind, dark theme)
│   ├── app/
│   │   ├── layout.tsx         # Root layout + theme + providers + AppShell
│   │   ├── page.tsx           # Login (default route)
│   │   ├── home/page.tsx      # Dashboard/landing
│   │   ├── login/page.tsx     # Retired URL → redirects to /
│   │   ├── vault/
│   │   │   ├── page.tsx       # Vault (unlock, encrypt/decrypt messages)
│   │   │   └── setup/page.tsx # Vault setup wizard (passphrase + share ceremony)
│   │   ├── beneficiaries/page.tsx  # CRUD + invites + share-index assignment
│   │   ├── heartbeat/page.tsx      # Config, check-in, status timeline, trigger
│   │   ├── recovery/page.tsx       # Beneficiary recovery stepper
│   │   ├── access/invite/[hash]/page.tsx  # Invitation accept
│   │   ├── settings/page.tsx       # Passphrase change + vault wipe
│   │   └── globals.css        # Design tokens (dark default, light-ready)
│   ├── components/            # shell, ui (modal/chips/toast), toast
│   ├── lib/
│   │   ├── api.ts             # Re-export shim (see api/ below)
│   │   ├── api/transport.ts   # Cookie fetch + safe JSON parsing
│   │   ├── api/owner.ts       # Owner-session wrappers
│   │   ├── api/beneficiary.ts # Beneficiary-session wrappers
│   │   ├── api/public.ts      # Login bootstrap (no retry)
│   │   ├── client.ts          # Backwards-compatible re-exports
│   │   ├── crypto.ts          # WebCrypto: PBKDF2, AES-GCM, AES-KW
│   │   ├── crypto-session.ts  # Sole holder of the unwrapped VMK
│   │   ├── shamir.ts          # Shamir GF(256) 2-of-3 (client only)
│   │   └── store/vault-context.tsx  # {unlocked, lock} — never the raw key
│   ├── tests/                 # Playwright: crypto unit (9), pages/redirects (11),
│   │                           # health (1), zero-knowledge boundary E2E (1)
│   ├── .env.local
│   └── package.json
│
├── backend/                   # FastAPI app
│   ├── main.py                # App setup + lifespan (heartbeat loop) + router includes
│   ├── config.py              # Pydantic settings
│   ├── db.py                  # SQLAlchemy engine/session
│   ├── deps.py                # Auth dependencies (owner/beneficiary)
│   ├── seed_dev_user.py       # Dev-only first-user seeder (no public signup by design)
│   ├── models/                # SQLAlchemy models (audit, beneficiary, category enum)
│   ├── routers/
│   │   ├── access.py          # Invite accept/status, cookie session refresh,
│   │   │                      # recovery message fetch (TRIGGERED-gated)
│   │   ├── auth.py            # Login/logout/refresh/me (tokens in cookies only)
│   │   ├── beneficiaries.py   # Beneficiary CRUD + invite + share assignment
│   │   ├── health.py          # Health check
│   │   ├── heartbeat.py       # Heartbeat config + check-in
│   │   ├── stats.py           # Dashboard stats
│   │   ├── trigger.py         # Vault trigger (confirm + idempotent) / dev reset
│   │   └── vault.py           # Message CRUD + crypto material + share-assignments alias
│   ├── services/
│   │   ├── auth.py            # Argon2id, JWT (owner 15m / beneficiary 30m), session mgmt
│   │   ├── audit.py           # Audit staging (add-only; callers own the commit)
│   │   ├── trigger_service.py # CAS state transitions (sole owner)
│   │   ├── heartbeat_checker.py  # Background evaluation + PENDING→SENT/FAILED delivery
│   │   └── notifications.py   # Mock by default (SendGrid/Twilio optional)
│   ├── alembic/               # Single explicit 0001_initial migration
│   ├── tests/                 # Pytest suite (118 tests passing)
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
| Key Derivation (Vault) | PBKDF2-SHA256 (600,000 iterations) |
| Key Derivation (Login) | Argon2id |
| Salt (vault KDF) | Random 16 bytes per vault |
| IV (per message) | Random 12 bytes |
| VMK Wrapping | AES-KW |
| Key Splitting | Shamir GF(256) 2-of-3 |
| JWT Algorithm | RS256 |
| Access Token TTL | 15 minutes |
| Refresh Token TTL | 30 days (rotating) |

**Message blob (per message):** `version || algorithm || iv || wrapped_MEK || ciphertext`, all base64-encoded.
**Wrapped VMK record:** `wrapped_vmk || PBKDF2-SHA256 params (salt, 600K iterations) || crypto version`.

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
| `/vault/crypto-material` | GET | Get wrapped VMK + KDF params |
| `/vault/crypto-material` | PUT | Save wrapped VMK (setup/passphrase change) |
| `/vault/messages` | POST | Save encrypted message |
| `/vault/messages` | GET | List messages |
| `/vault/messages/{id}` | GET | Get message |
| `/vault/messages/{id}` | PUT | Update message |
| `/vault/messages/{id}` | DELETE | Delete message |
| `/vault/messages` | DELETE | Wipe all messages (password + confirm) |
| `/vault/share-assignments` | GET | Share-index assignments (metadata only) |

### Beneficiaries
| Route | Method | Purpose |
|-------|--------|---------|
| `/beneficiaries` | POST | Add beneficiary (optional share_index) |
| `/beneficiaries` | GET | List beneficiaries |
| `/beneficiaries/{id}` | PUT | Update beneficiary (incl. share_index) |
| `/beneficiaries/{id}` | DELETE | Remove beneficiary |
| `/beneficiaries/{id}/invite` | POST | Send invitation (returns out-of-band link) |
| `/beneficiaries/{id}/assign-share` | POST | Assign share index 1–3 (metadata only) |

### Access (Beneficiary)
| Route | Method | Purpose |
|-------|--------|---------|
| `/access/invite/{hash}/status` | GET | Check invitation |
| `/access/invite/{hash}/accept` | POST | Accept invitation (single-use, rotates) |
| `/access/session` | POST | Refresh beneficiary session (30 min) |
| `/access/status` | GET | Beneficiary access status (TRIGGERED-gated) |
| `/access/share` | POST | Submit share hash (idempotent, TRIGGERED-gated) |
| `/access/share/report-mismatch` | POST | Report failed reconstruction (INV-20 counter) |
| `/access/messages` | GET | List message metadata (TRIGGERED-gated) |
| `/access/messages/{id}` | GET | Get ciphertext + wrapped MEK (TRIGGERED-gated) |

### Access (Owner)
| Route | Method | Purpose |
|-------|--------|---------|
| `/access/share-assignments` | GET | List share assignments (metadata only) |

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
| `/vault/trigger` | POST | Manually trigger vault (password + confirm, idempotent) |
| `/vault/reset-status` | POST | Reset to active (non-production only) |

### Stats
| Route | Method | Purpose |
|-------|--------|---------|
| `/stats` | GET | Dashboard statistics |

All routes require valid JWT in Authorization header or HttpOnly cookie, except
`GET /health[/z]`, `GET /readyz`, and the public invitation endpoints
(`GET /access/invite/{hash}/status`, `POST /access/invite/{hash}/accept`).
Owner vs beneficiary roles are enforced separately on every other route.

---

## Local Development

### Prerequisites
- Docker Desktop (for PostgreSQL)
- Node.js 18+ / Python 3.11+
- OpenSSL (for generating secrets — ships with Git for Windows)

### First-time setup

```bash
# 1. From the repo root: copy env template and set a session secret (>=32 chars)
cp .env.example .env
# Edit .env and replace SESSION_SECRET, e.g. output of: openssl rand -base64 48

# 2. Generate JWT signing keys (backend/keys/ is gitignored)
openssl genrsa -out backend/keys/jwt_private.pem 2048
openssl rsa -in backend/keys/jwt_private.pem -pubout -out backend/keys/jwt_public.pem

# 3. Start PostgreSQL (from repo root — the compose file lives here)
docker compose up -d postgres

# 4. Backend: venv + deps
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# 5. Create your owner login (no signup endpoint by design — seed one user).
# Tables are auto-created on first boot in development; no alembic step needed.
venv\Scripts\python seed_dev_user.py owner@example.com   # Windows (prompts for password, 12+ chars)
# python seed_dev_user.py owner@example.com              # macOS/Linux

# 6. Frontend: deps (from repo root)
cd ../frontend
npm install
cp .env.local.example .env.local   # optional — defaults to http://localhost:8000
```

> Use a real-looking email for the seed user (e.g. `owner@example.com`):
> login validation rejects special-use domains like `.local`.

### Daily boot (three terminals, repo root)

```bash
# Terminal 1 — database
docker compose up -d postgres

# Terminal 2 — backend (http://localhost:8000, health at /health)
cd backend
venv\Scripts\activate          # Windows
uvicorn main:app --reload --port 8000

# Terminal 3 — frontend (http://localhost:3000)
cd frontend
npm run dev
```

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API / health | http://localhost:8000 / http://localhost:8000/health |
| pgAdmin (optional) | http://localhost:5050 (see `PGADMIN_*` in `.env`) |

To stop: `Ctrl+C` the two servers, then `docker compose stop postgres`
(full reset of dev data: `docker compose down -v`).

### 5-minute demo walkthrough

1. Open http://localhost:3000/ and log in with your seeded user.
2. **Vault setup** (`/vault/setup`): enter a vault passphrase (12+ chars, distinct
   from login) → wrapped VMK is saved, 3 Shamir shares display **once** — copy them
   somewhere safe (out-of-band; the app never sends them anywhere).
3. **Vault** (`/vault`): unlock with the passphrase, create 2–3 messages
   (encrypted in-browser via AES-256-GCM before upload).
4. **Beneficiaries** (`/beneficiaries`): add 3 beneficiaries, hit Invite, send each
   link yourself (email is mock-logged in dev).
5. **Heartbeat** (`/heartbeat`): save a short interval for demo (e.g. 1 day / 1 day
   grace via API), check in, then trigger manually (password + confirm).
6. **Recovery** (`/recovery`): as a beneficiary, paste any 2 shares + a message's
   `ciphertext`/`wrapped_mek`/`iv` → VMK reconstructs and decrypts locally.

### Run Tests
```bash
# Backend (118 tests; file SQLite via Alembic, no Postgres needed)
cd backend
venv\Scripts\python -m pytest tests/ -v

# Frontend
cd frontend
npm run typecheck
npm run build
npx playwright test            # needs `npx playwright install chromium` once + `npm run dev` on :3000
```

### Troubleshooting
- `column ... of relation ... does not exist` after pulling: your Postgres volume
  predates the current schema — `docker compose down -v && docker compose up -d postgres`
  (dev data only), then re-run `seed_dev_user.py`.
- `value is not a valid email address ... special-use or reserved name`: use
  `owner@example.com`, not `.local`.
- `JWT private key not configured`: you skipped step 2 (keygen) above.
- Port busy (`8000`/`3000`/`5432`): stop the other process or change the port
  (`uvicorn ... --port 8001`, `next dev -p 3001` + matching `NEXT_PUBLIC_API_URL`).

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
- Beneficiary CRUD with invitation flow (hash-stored, single-use, expiring links)
- Share-index assignment (metadata only — raw shares never touch the server)
- Invitation accept → short-lived beneficiary session
- Share-hash submission (idempotent) + mismatch lockout (INV-20)
- Beneficiary ciphertext fetch after trigger → local reconstruct + decrypt
  (backend never reconstructs the VMK)

**Phase 3: Heartbeat / Dead Man's Switch**
- Heartbeat config (interval + grace period)
- Check-in endpoint + background checker
- State machine: active → grace → triggered (CAS, idempotent)
- Escalating notifications during grace period (mock-logged in dev)
- Trigger notifications to beneficiaries

**Infrastructure**
- PostgreSQL with auto-created dev schema (+ Alembic migrations)
- Docker Compose for local dev
- 118 backend tests passing
- Frontend TypeScript build passing
- E2E tests (Playwright: crypto unit + page/redirect specs)

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