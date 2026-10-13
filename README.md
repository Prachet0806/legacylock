# LegacyLock

LegacyLock encrypts secret messages in the browser and permits enrolled beneficiaries to fetch ciphertext after an owner-authorized or heartbeat release. Recovery requires separately held Shamir shares. Login passwords reach the authentication service; vault passphrases, plaintext, unwrapped vault/message keys and recovery shares do not reach application APIs. Labels, categories, email addresses, assignments and timing remain server-visible metadata. A malicious delivery of application JavaScript is outside the protection offered by encrypted database storage.

Implementation status and remaining release gates are recorded in [the remediation implementation record](docs/remediation-implementation.md). The prior README and deployment guide are preserved in `docs/archive/` as historical material; current commands and contracts are below and in [DEPLOY.md](DEPLOY.md).

## Current behavior

- Initial key setup is an inactive draft until all generated shares are acknowledged and the complete wrapping bundle/policy finalizes atomically. Restarting a draft generates fresh shares. Initialized vaults cannot run destructive setup again.
- Passphrase changes rewrap the same vault key with a new salt and expected material revision. Existing messages and shares continue to work. Resharing uses a replacement ceremony and retains the existing key; old quorums remain able to reconstruct it.
- A check-in explicitly arms heartbeat release. All eligibility writers and release transitions serialize on the vault status row. Grace starts at the missed deadline. Production release is terminal; creation/editing/key changes stop, while owner reading, export and deletion remain available.
- Registration requires an operator invitation code and email verification. Enrolled beneficiaries can request fresh, single-use email sign-in links without the original invitation or browser cookies. Before release they see waiting status without ciphertext access.
- Owner and beneficiary cookies represent independent revocable session families. Refresh rotates once, uses cross-tab exclusion where supported and detects replay. Logout and recipient contact replacement invalidate the corresponding authorization.
- Business mutations stage durable audit and delivery intent in the same transaction. A separate leased worker sends email with provider idempotency, retries and dead-letter evidence. Provider acceptance does not prove inbox delivery. SMS is optional and disabled by default.
- Readiness separates initialization, finalized ceremony, current accepted share assignments, explicit arming and owner-reported local drill evidence. Assignment does not prove share possession or independent recovery.

## Runtime and development

Declared build targets: Python 3.12.14, Node 22.23.3, Next 15.5.27, React 18.3.1 and PostgreSQL 17. Backend dependencies use `requirements.lock.txt` as the constraints source; frontend installs use `package-lock.json`. Check [dependency exceptions](docs/dependency-exceptions.md) before release.

Copy `.env.example` into your local environment and configure a development database and JWT pair. Backend settings load `../.env` when run from `backend/`. Generate development keys only; never reuse them in production:

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

Set `API_UPSTREAM` before a production build. The rewrite is baked into the build; changing only the runner environment does not rebuild it. Use same-origin `/api` in the browser. Independent cross-site cookie deployment is outside the qualified topology.

For a separate worker, set `BACKGROUND_IN_API=false` on the API and run `python worker.py` from `backend/` with matching database, hold, delivery key ring, epoch and provider settings. The worker needs no JWT private key. Do not run the old notification sender alongside it.

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

Sanitized inventory is `python ops.py`. Encrypted local restoration, held recovery and cutover procedures are described in [the operations runbook](docs/remediation-operations.md). The design and API contracts are in [remediation contracts](docs/remediation-contracts.md).
