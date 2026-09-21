# LegacyLock — Production Deployment Guide (Side Project)

Target: **single VPS + Vercel + managed DNS, email-only notifications**.
This is a side project with no scale expectations (~$6–16/month).

```
Browser → https://app.example.com (Vercel, Next.js)
            └─ /api/* ──rewrite──▶ https://api.example.com/* (VPS, Caddy → backend:8000)
                                   (prefix stripped — backend routes are unversioned)

VPS (Docker Compose): Caddy (TLS) + backend (FastAPI, exactly 1 instance) + Postgres
Email: Resend (free tier). SMS: intentionally disabled (mock-logged).
```

Same-origin `/api` is preserved via Vercel rewrites so `SameSite=Lax`
HttpOnly cookies keep working. Do NOT call the API origin directly from the
browser — split-origin (`NEXT_PUBLIC_API_URL=https://api...`) is untested and
breaks cookie auth (would require `SameSite=None`; see Known limits).

Assumes: `main` is green in CI (pytest, lint, typecheck, build, E2E, images).

---

## 0. What you need (~30 min one-time)

- A VPS (Hetzner CX22 / DigitalOcean 2GB / Linode 2GB class, ~$5–10/mo)
  with Docker + Docker Compose plugin installed.
- A domain managed in Cloudflare (free DNS + proxy optional).
- A Vercel account (free tier) + Resend account (free tier, 3k emails/mo).
- `openssl` locally for secret generation.

### 0.1 DNS

| Host | Target | Notes |
|---|---|---|
| `app.example.com` | Vercel (CNAME per Vercel domain docs) | Frontend |
| `api.example.com` | VPS public IP (A record, DNS-only during first Caddy issuance, proxy OK after) | Backend |

TLS:
- `app.*`: automatic via Vercel.
- `api.*`: automatic via Caddy (ACME HTTP/TLS-ALPN on ports 80/443).
  All traffic below assumes HTTPS.

### 0.2 Resend (chosen over SendGrid — see why below)

1. Create a Resend API key (free tier: 3,000 emails/mo).
2. Add + verify your sending domain in Resend (apex or `mail.` subdomain):
   add the SPF/DKIM TXT records Resend shows you, wait for Verified.
3. Set sender to something on that domain, e.g. `noreply@example.com`.
   Sandbox senders (`onboarding@resend.dev`) only deliver to your own
   Resend account address — fine for staging, not for prod.

> Why Resend over SendGrid: same free-tier volume (3k/mo), cheaper paid tier
> ($10 vs $19.95 per 50k), simpler API, and the backend already integrates
> Resend (`services/notifications.py`). Pick SendGrid only if you need its
> advanced analytics, HIPAA certs, or enterprise support.

### 0.3 Secrets — generate once, keep on the VPS only

```bash
openssl rand -base64 48                                   # SESSION_SECRET
openssl genrsa -out jwt_private.pem 2048                  # JWT signing key
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
openssl rand -hex 16                                      # REGISTRATION_INVITE_CODE
```

Never commit these. Never reuse dev keys. Required values on the VPS:

| Name | Value |
|---|---|
| `SESSION_SECRET` | rand output (≥32 chars, enforced) |
| `DATABASE_URL` | `postgresql+psycopg://legacylock:<strong-pw>@postgres:5432/legacylock_prod` |
| `POSTGRES_PASSWORD` | strong password for the Compose Postgres service |
| `JWT_PRIVATE_KEY_PATH` | `/run/secrets/jwt_private.pem` (mounted file) |
| `JWT_PUBLIC_KEY_PATH` | `/run/secrets/jwt_public.pem` |
| `ALLOWED_ORIGINS` | `https://app.example.com` |
| `FRONTEND_URL` | `https://app.example.com` |
| `ENVIRONMENT` | `production` |
| `TRUSTED_PROXIES` / `FORWARDED_ALLOW_IPS` | empty on single VPS (Caddy is local); set only if Cloudflare-proxied headers are trusted |
| `HEARTBEAT_ENABLED` | `true` |
| `REGISTRATION_INVITE_CODE` | rand-hex (gated signup; empty = disabled, fail-closed) |
| `RESEND_API_KEY` | `re_...` (empty = mock-log; prod must be set or notifications silently no-op) |
| `NOTIFICATION_EMAIL_FROM` | `noreply@example.com` (must be on your verified Resend domain) |

Email-only by design: leave `TWILIO_*` unset. SMS stays mock-logged and no
SMS is ever required for grace/trigger flows.

---

## 1. VPS services

Run exactly these on the VPS (see example below — adapt paths to your host):

```yaml
# docker-compose.prod.yml (example — keep this file on the VPS, not in git
# if it ever contains real secrets; prefer an env file with chmod 600)
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: legacylock
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: legacylock_prod
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  backend:
    build: ./backend   # or image: registry.example.com/legacylock-backend:<sha>
    environment:
      ENVIRONMENT: production
      DATABASE_URL: postgresql+psycopg://legacylock:${POSTGRES_PASSWORD}@postgres:5432/legacylock_prod
      SESSION_SECRET: ${SESSION_SECRET}
      ALLOWED_ORIGINS: https://app.example.com
      FRONTEND_URL: https://app.example.com
      JWT_PRIVATE_KEY_PATH: /run/secrets/jwt_private.pem
      JWT_PUBLIC_KEY_PATH: /run/secrets/jwt_public.pem
      HEARTBEAT_ENABLED: "true"
      REGISTRATION_INVITE_CODE: ${REGISTRATION_INVITE_CODE}
      RESEND_API_KEY: ${RESEND_API_KEY}
      NOTIFICATION_EMAIL_FROM: ${NOTIFICATION_EMAIL_FROM}
    secrets:
      - jwt_private
      - jwt_public
    depends_on: [postgres]
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [backend]
    restart: unless-stopped

secrets:
  jwt_private:
    file: ./keys/jwt_private.pem
  jwt_public:
    file: ./keys/jwt_public.pem

volumes:
  postgres_data:
  caddy_data:
  caddy_config:
```

```caddyfile
# Caddyfile (on the VPS alongside the compose file)
api.example.com {
    # Strip /api only if clients ever send it; Vercel already strips it.
    # Backend routes are unversioned: /auth/*, /vault/*, /health, /readyz, ...
    reverse_proxy backend:8000
}
```

Notes:
- Backend runs as **exactly 1 instance** (in-process heartbeat loop +
  in-memory rate buckets — do not scale out).
- `keys/` is dockerignored from the image; keys arrive via Compose secrets.
- Uvicorn must run with `--proxy-headers` (already the Dockerfile default)
  since Caddy terminates TLS.
- Keep the dev `docker-compose.yml` services (`pgadmin`) out of prod.

## 2. Database migration (runs BEFORE the new backend starts)

```bash
# One-shot, on the VPS, with prod env + secrets loaded:
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
# Expected: ... -> 0001_initial (+ any later heads), no errors.
```

Never run migrations from app boot and never `init_db` in production
(the app skips it when `ENVIRONMENT=production`).

## 3. Frontend on Vercel

1. Import the repo's `frontend/` directory as a Vercel project.
2. Production Environment Variables in Vercel:
   - `NEXT_PUBLIC_API_URL=` (empty string = same-origin `/api`, required).
     It is BAKED IN at build time — changing it requires a redeploy.
3. Add `vercel.json` to `frontend/` so `/api` stays same-origin
   (this is what keeps `SameSite=Lax` cookies working):

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://api.example.com/:path*" }
  ]
}
```

> `next.config.mjs` only rewrites `/api` in dev; production relies on this
> edge rewrite. The `:path*` destination strips the prefix (backend is
> unversioned).

4. Assign `app.example.com` to the Vercel project; wait for TLS to go green.
5. Every PR gets a preview URL automatically — point previews at staging
   (or accept that `/api` rewrite hits prod; prefer a staging backend).

## 4. Backups (cheap, good enough for a side project)

```bash
# Nightly cron on the VPS (adjust paths):
0 3 * * * docker exec legacylock-postgres-1 pg_dump -U legacylock legacylock_prod | gzip > /root/backups/legacylock-$(date +\%F).sql.gz && find /root/backups -mtime +14 -delete
```

- Optionally `rclone copy` the dump to R2/S3 (~$0.01/mo).
- Do one restore drill to a scratch DB before going live, then quarterly.

## 5. Smoke test

1. `GET https://api.example.com/health` → 200 (via Caddy).
   `GET https://api.example.com/readyz` → 200 (DB-checked).
   `GET https://app.example.com/api/health` → 200 (via Vercel rewrite).
2. Gated signup: `POST /auth/register` with `REGISTRATION_INVITE_CODE` →
   verify link from Resend → login at `/`, confirm `Secure` HttpOnly cookies.
   Negative: login before verification → `403`.
3. Golden path: setup → 1–3 messages → beneficiaries → trigger → 2-share
   recovery → plaintext matches (mirror of
   `tests/zero_knowledge_network_boundary.spec.ts`).
4. Negative checks: `POST /vault/shares` → 404, raw `share` field → 422,
   weak KDF iterations → 422, cross-tenant message id → 404, wrong `Origin` → 403.
5. Prod CSP on HTML includes your prod origin in `connect-src`; cookies are
   `Secure`. Confirm Resend dashboard shows deliveries (not mock-logs).

## 6. Operate

- Logs: `docker compose -f docker-compose.prod.yml logs -f backend` (+ optional
  Uptime Kuma on the VPS polling `/readyz`).
- Updates: `git pull` → rebuild backend image → `alembic upgrade head` →
  `up -d`. Frontend: push to `main` → Vercel auto-deploys.
- Rotation (manual, ~yearly): new `SESSION_SECRET`/JWT pair → restart;
  refresh families re-mint on next use. Treat any exposed private key as
  compromised and rotate immediately.

## Rollback

- Backend: redeploy the previous image/git SHA (`up -d --force-recreate`).
- Frontend: Vercel → Deployments → Promote previous production deployment.
- Migrations are additive-only: rolling back code never requires rolling back
  the database. If a migration ever drops something, write its rollback plan
  before shipping.

## Known limits (accepted for a side project — fix properly only if it grows)

- Backend is single-instance (heartbeat + rate limits are in-process).
  No failover; deploys cause brief downtime.
- Email-only notifications. SMS stays mock-logged until `TWILIO_*` is
  configured (not planned).
- No `SameSite=None` support: direct cross-origin API calls are unsupported;
  always go through the same-origin `/api` rewrite.
- No password/account recovery (by design — users who lose login or vault
  passphrase are locked out). Manual JWT/secret rotation only.
- No audit-log UI, metrics stack, or read replicas — use DB shell, `docker
  logs`, and Uptime Kuma.
- Remaining `npm audit` critical is Next.js itself (no 14.x fix; affected
  features — Image Optimizer/rewrites — are unused).
