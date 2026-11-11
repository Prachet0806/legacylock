# LegacyLock

LegacyLock encrypts secret messages in the browser and permits enrolled beneficiaries to fetch ciphertext after an owner-authorized or heartbeat release. Recovery requires separately held Shamir shares. Login passwords reach the authentication service; vault passphrases, plaintext, unwrapped vault/message keys and recovery shares do not reach application APIs. Labels, categories, email addresses, assignments and timing remain server-visible metadata. A malicious delivery of application JavaScript is outside the protection offered by encrypted database storage.

Current behavior and development commands are below. Hosting, cutover, and remaining release gates are in [DEPLOY.md](DEPLOY.md).

## Current behavior

- Initial key setup is an inactive draft until all generated shares are acknowledged and the complete wrapping bundle/policy finalizes atomically. Restarting a draft generates fresh shares. Initialized vaults cannot run destructive setup again.
- Passphrase changes rewrap the same vault key with a new salt and expected material revision. Existing messages and shares continue to work. Resharing uses a replacement ceremony and retains the existing key; old quorums remain able to reconstruct it.
- A check-in explicitly arms heartbeat release. All eligibility writers and release transitions serialize on the vault status row. Grace starts at the missed deadline. Production release is terminal; creation/editing/key changes stop, while owner reading, export and deletion remain available.
- Registration requires an operator invitation code and email verification. Enrolled beneficiaries can request fresh, single-use email sign-in links without the original invitation or browser cookies. Before release they see waiting status without ciphertext access.
- Owner and beneficiary cookies represent independent revocable session families. Refresh rotates once, uses cross-tab exclusion where supported and detects replay. Logout and recipient contact replacement invalidate the corresponding authorization.
- Business mutations stage durable audit and delivery intent in the same transaction. In the selected Free deployment, the in-process scheduler leases and sends email with provider idempotency, retries and dead-letter evidence; the optional paid topology runs this in a separate worker. Provider acceptance does not prove inbox delivery.
- Readiness separates initialization, finalized ceremony, current accepted share assignments, explicit arming and owner-reported local drill evidence. Assignment does not prove share possession or independent recovery.

## Runtime and development

Declared build targets: Python 3.12.14, Node 22.23.3, Next 15.5.28, React 18.3.1 and PostgreSQL 17. Backend dependencies use `requirements.lock.txt` as the constraints source; frontend installs use `package-lock.json`. Run dependency audits before release.

Copy `.env.example` into your local environment and configure a development database and JWT pair. Backend settings load `../.env` when run from `backend/`. Generate development keys only; never reuse them in production:

The root `.env` is for a backend run directly or for local Docker Compose. The frontend uses `frontend/.env.local`; copy `frontend/.env.local.example` there for local development. Browser API calls stay at `/api`, and `API_UPSTREAM` points Next to the backend. The local Compose file forwards backend settings from the root `.env`, including `REGISTRATION_INVITE_CODE`. For hosted services, use the separate inventories under `deploy/` and the [deployment contract](DEPLOY.md); keep credentials in the service secret stores.

The selected hosted footprint is Vercel frontend → Render Free API → Neon Free PostgreSQL. The API runs the single-process scheduler, so this topology has no separate worker. Local Compose remains a disposable PostgreSQL development database. At the repository root, Neon CLI `neon init`/`neon env pull` writes `DATABASE_URL` and `DATABASE_URL_UNPOOLED` to the ignored `.env`; the backend loads `DATABASE_URL` and normalizes Neon’s `postgresql://` URL to SQLAlchemy’s `psycopg` driver. Set the Render service's `DATABASE_URL` to Neon’s direct/unpooled endpoint and use that direct endpoint for Alembic migrations. The scheduler holds a session-level advisory lock while it runs; Neon transaction pooling does not support session-level advisory locks, so a hostname containing `-pooler` is incompatible with this topology. Production preflight rejects a Neon pooler hostname when `TASK_MODE=single_process_demo`. Keep connection strings server-side; never put them in `NEXT_PUBLIC_*` or another browser variable. See [DEPLOY.md](DEPLOY.md) for the Free-tier limits, migration procedure, monitoring, and optional paid-worker alternative.

```sh
mkdir -p backend/keys
openssl genrsa -out backend/keys/jwt_private.pem 2048
openssl rsa -in backend/keys/jwt_private.pem -pubout -out backend/keys/jwt_public.pem
cd backend
python -m venv .venv
# Activate .venv (Windows: .venv/Scripts/Activate.ps1)
python -m pip install -r requirements-dev.txt
alembic upgrade head
python seed_dev_user.py owner@example.com DevPassword123456
uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

The seeded credentials above are synthetic local fixtures. Registration otherwise needs `REGISTRATION_INVITE_CODE`. Development suppresses provider calls without credentials and logs no email bodies; it does not exercise real inbox delivery.

In another terminal:

```sh
cd frontend
npm ci
# Local defaults: NEXT_PUBLIC_API_URL=/api, API_UPSTREAM=http://localhost:8000
npm run dev
```

For a frontend-only Vercel deployment, `API_UPSTREAM` may be omitted; the app builds without an `/api` proxy and API-dependent features remain unavailable. Set the real HTTPS `API_UPSTREAM` before the build that enables backend features. The rewrite is baked into the build; changing only the runner environment does not rebuild it. Use same-origin `/api` in the browser. Independent cross-site cookie deployment is outside the qualified topology.

For the optional paid separate-worker topology, set `BACKGROUND_IN_API=false` on the API and run `python worker.py` from `backend/` with matching database, hold, delivery key ring, epoch and provider settings. The worker needs no JWT private key. Do not run it alongside the in-process scheduler; do not run the old notification sender alongside either mode.

## Verification

Run backend commands from `backend/`:

```sh
python -m pytest tests -q
python ../scripts/quality_gate.py
pip-audit -r requirements.lock.txt --no-deps --disable-pip
# PostgreSQL profile: USE_POSTGRES=1 and TEST_DATABASE_URL=postgresql+psycopg://.../isolated_test
```

Both pytest profiles build schema through Alembic. PostgreSQL race tests deliberately skip on SQLite. The quality gate has hard import/correctness lint checks plus a reviewed diagnostic ratchet; the repository is not fully type-clean.

For browser qualification, start a backend with `ENVIRONMENT=test`, `USE_POSTGRES=1`, `MIGRATED_SCHEMA_ONLY=true`, `HEARTBEAT_ENABLED=false` and an independently migrated test database. Set the test invitation code and seed owner. Then:

```sh
cd frontend
npm run lint
npm run typecheck
npm run audit
npm audit --omit=dev --audit-level=high
# Build with NEXT_PUBLIC_API_URL=/api and API_UPSTREAM=http://localhost:8000
npm run build
npx playwright install chromium
# E2E_PRODUCTION=1 and CI=1 make the suite use standalone output and fail on missing fixtures.
npm run test:e2e
```

Do not set the direct test-helper API URL to `/api`: test request contexts default to `http://localhost:8000`; the browser bundle independently uses `/api`. Stateful journeys create unique owners. Test mailbox/time-travel routes exist only in test mode and must never be deployed as production mode substitutes.

Sanitized inventory is `python ops.py`. Deployment and cutover requirements are in [DEPLOY.md](DEPLOY.md); the original design and API specifications are in [the numbered documentation](docs/legacylock-docs/00-overview.md).
