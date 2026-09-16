# LegacyLock — Production Deployment Guide

Target: **managed PaaS + managed Postgres, single domain** (`https://app.example.com`)
with same-origin `/api` proxying. Backend runs as **exactly 1 instance**
(in-process heartbeat loop + in-memory rate buckets — do not scale out yet).

Assumes: `main` is green in CI (pytest, lint, typecheck, build, E2E, images).

---

## 0. One-time setup (~30 min)

### 0.1 DNS + TLS
1. Point `app.example.com` at your PaaS (CNAME / ALIAS per provider docs).
2. Enable automatic TLS on the PaaS router. All traffic below assumes HTTPS.

### 0.2 Managed Postgres
1. Provision Postgres 16 with TLS enforced.
2. Note the connection string, e.g.
   `postgresql+psycopg://legacylock:<pw>@<host>:5432/legacylock_prod?sslmode=require`
3. Enable automated backups + point-in-time recovery. Do one restore drill to a
   scratch DB before going live (step 5.4).

### 0.3 Secrets — generate once, store in the platform secret manager
```bash
openssl rand -base64 48                                   # SESSION_SECRET
openssl genrsa -out jwt_private.pem 2048                  # JWT signing key
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```
Never commit these. Never reuse dev keys. Required secrets:

| Name | Value |
|---|---|
| `SESSION_SECRET` | output of the rand command (≥32 chars, enforced) |
| `DATABASE_URL` | prod connection string above |
| `JWT_PRIVATE_KEY_PATH` | `/run/secrets/jwt_private.pem` (mounted file) |
| `JWT_PUBLIC_KEY_PATH` | `/run/secrets/jwt_public.pem` |
| `ALLOWED_ORIGINS` | `https://app.example.com` |
| `FRONTEND_URL` | `https://app.example.com` |
| `ENVIRONMENT` | `production` |
| `TRUSTED_PROXIES` / `FORWARDED_ALLOW_IPS` | your LB CIDRs |
| `HEARTBEAT_ENABLED` | `true` |

Optional now, needed later: `TWILIO_*`.
Required for self-service signup: `REGISTRATION_INVITE_CODE`
(`openssl rand -hex 16`, distributed out-of-band), `RESEND_API_KEY`
(sandbox sender works for staging; prod needs a verified custom domain with
SPF/DKIM/DMARC), `NOTIFICATION_EMAIL_FROM`.

---

## 1. Build images

```bash
# Backend (no secrets inside — keys/ is dockerignored, verified in CI review)
docker build -t registry.example.com/legacylock-backend:<sha> ./backend

# Frontend. NEXT_PUBLIC_API_URL is BAKED IN at build time:
# empty string = same-origin /api (recommended — this guide assumes it).
docker build -t registry.example.com/legacylock-frontend:<sha> \
  --build-arg NEXT_PUBLIC_API_URL= ./frontend

docker push registry.example.com/legacylock-backend:<sha>
docker push registry.example.com/legacylock-frontend:<sha>
```

## 2. Migrate the database (release job, runs BEFORE the new backend starts)

```bash
# One-shot job with the backend image + prod env + secrets mounted:
alembic upgrade head
# Expected: ... -> 0001_initial (+ any later heads), no errors.
# Verify: all 9 tables + partial unique indexes exist.
```

Never run migrations from app boot (replicas would race); never `init_db` in
production (the app skips it when `ENVIRONMENT=production`).

## 3. Platform services

| Service | Image | Command / config | Replicas |
|---|---|---|---|
| `web` | frontend | `node .next/standalone/server.js`, port 3000 | 1+ |
| `api` | backend | `uvicorn`, port 8000, `--proxy-headers`, LB allow-list | **exactly 1** |

Routing on `app.example.com`:
- `/api/*` → `api:8000/*` (**strip the `/api` prefix** — backend routes are unversioned)
- everything else → `web:3000`
- Health for load-balancer checks: backend `/readyz` (DB-checked), **not** `/healthz` (static).

Mount JWT key files into `api` at `/run/secrets/`. Attach all secrets from 0.3.
Set resource limits; keep `pgadmin` and local `docker-compose.yml` services out
of production entirely.

## 4. Smoke test staging first

Deploy everything above to a staging domain first, then:

1. `GET /health` → 200, `GET /readyz` → 200.
2. Create an owner either out-of-band (`seed_dev_user.py` against staging DB
   via a one-off job) or via gated signup (`POST /auth/register` with
   `REGISTRATION_INVITE_CODE` → verify link → login at `/`), confirm `Secure`
   HttpOnly cookies. Negative: login before verification → `403`.
3. Golden path: setup → 3 messages → 3 beneficiaries → trigger → 2-share
   recovery → plaintext matches (mirror of `tests/zero_knowledge_network_boundary.spec.ts`).
4. Negative checks: `POST /vault/shares` → 404, raw `share` field → 422,
   weak KDF iterations → 422, cross-tenant message id → 404, wrong `Origin` → 403.
5. Response headers on HTML include the CSP with your prod origin in
   `connect-src`; cookies are `Secure`.

## 5. Go live + operate

1. Promote staging images to prod (same SHAs — never rebuild between stages).
2. Run the release-job migration against prod, then deploy.
3. Re-run section 4 against prod (read-only checks + one golden run with a
   throwaway owner you delete afterwards).
4. PITR restore drill (from 0.2) at least once per quarter.
5. Rotation: new `SESSION_SECRET`/JWT pair → rolling restart; refresh families
   re-mint on next use. Treat any exposed private key as compromised (see repo
   history note in README) and rotate immediately.

## Rollback

Images are tagged by SHA — roll back by redeploying the previous SHA.
Migrations are additive-only: rolling back code never requires rolling back
the database. If a migration ever drops something, that deploy needs its own
rollback plan written before shipping.

## Known limits (do not work around — fix properly later)

- Backend is single-instance (heartbeat + rate limits are in-process).
- No `SameSite=None` support: split-origin deployments are untested; stay
  same-origin.
- SMS is mock-logged until `TWILIO_*` keys are configured (email sends via Resend once `RESEND_API_KEY` is set).
- Remaining `npm audit` critical is Next.js itself (no 14.x fix; affected
  features — Image Optimizer/rewrites — are unused).
