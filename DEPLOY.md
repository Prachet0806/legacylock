# LegacyLock deployment contract

Production activation requires the checks below and current dependency audits. Local tests do not establish real email delivery, HTTPS cookie behavior, offsite backup objectives, capacity or independent cryptographic review.

## Topology and artifact

Browser → Vercel HTTPS application origin → same-origin `/api/*` rewrite → Northflank FastAPI service → Supabase PostgreSQL. A second, private Northflank service runs `python worker.py` continuously for checker passes and delivery attempts. Keep one API instance while rate limits use process-local buckets. Rolling replacement also needs edge enforcement if the limit must span old/new instances. Never trust arbitrary forwarded headers to improve client-IP attribution.

Build the backend image from the reviewed tree and use a native Vercel build from `frontend/` with `npm ci` and `npm run build`. Targets are Python 3.12.14 and Node 22.23.3; install locked dependencies. Set `NEXT_PUBLIC_API_URL=/api` and `API_UPSTREAM=<Northflank production HTTPS API origin>` for production. For Vercel previews set `PREVIEW_API_UPSTREAM=<isolated HTTPS fixture API origin>` and `PRODUCTION_API_UPSTREAM=<production HTTPS API origin>`; the build rejects a missing or shared preview origin. The Next.js rewrite is the sole `/api` route. The frontend Docker image is a diagnostic artifact whose standalone `server.js` needs `.next/static` colocated.

`render.yaml` is a historical deployment example and is not used for this topology. Configure exactly one Northflank API service from `backend/Dockerfile`, one independent worker service from the same reviewed image, and a one-off migration job before deploying the worker. Gate automatic promotion of API and worker so schema and sender cutover stay coordinated. Qualify the actual accounts, quotas and host behavior before storing real user data. Supabase Free has no automatic daily backup or PITR; arrange and test encrypted offsite backups separately.

## Required configuration

| Setting | Contract |
|---|---|
| `ENVIRONMENT` | `production` on API and worker |
| `DATABASE_URL` | Supabase session/direct PostgreSQL URL with certificate-verified TLS (`sslmode=verify-full`); use an endpoint compatible with the host's IP support, backed up and isolated from test databases |
| `SESSION_SECRET` | Dedicated random value, at least 32 characters |
| `AUTH_EPOCH` | Deployment-wide identifier, synchronized on API/worker; replace after restoration |
| JWT signing keys | Corresponding RSA private/public PEM pair, at least 2048 bits. API validates correspondence at startup. Supply readable files via `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, or base64-encoded PEMs via secret-store `JWT_PRIVATE_KEY_B64`/`JWT_PUBLIC_KEY_B64` when mounted file permissions prevent non-root access. Worker needs neither key |
| `DELIVERY_PAYLOAD_KEY` | Separate random 32-byte base64 AES-GCM key, backed up outside the database |
| `DELIVERY_PAYLOAD_KEY_ID`, `DELIVERY_PAYLOAD_KEYS` | Current version and secret JSON ring of retained older versions; do not retire a version with live/retained payloads |
| `ALLOWED_ORIGINS`, `FRONTEND_URL` | Exact application HTTPS origin; no wildcard or `null` |
| `ALLOWED_HOSTS` | Actual API hostnames, including platform health/rewrite host |
| `TRUSTED_PROXIES` | Verified direct-peer and forwarding-chain CIDRs only. Start Uvicorn with `--no-proxy-headers`; the application owns trust parsing |
| `BACKGROUND_IN_API` | `false` with the separate worker |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` | Bounded SQLAlchemy connections for the Supabase limit; defaults 3, 0, 10 seconds per process; verify total API plus worker connection usage |
| `MAX_BENEFICIARIES_PER_VAULT`, `MAX_MESSAGES_PER_VAULT` | Admission limits, defaults 25 and 100; tune only after hosted capacity measurement |
| `HEARTBEAT_ENABLED` | `true` for recovery checking |
| `RELEASE_HOLD` | Initially `true` on both processes; release only after reconciliation and evidence review |
| `DELIVERY_ENABLED` | `false` during restore quarantine; enable deliberate delivery after reconciliation |
| `RESEND_API_KEY`, `NOTIFICATION_EMAIL_FROM` | Real verified sender/account; missing email credentials fail production startup. Verify domain, quota and delivery using a controlled recipient |
| `OPERATIONS_TOKEN` | Separate random credential for the restricted recovery-health monitor |
| `REGISTRATION_INVITE_CODE` | Out-of-band operator enrollment code; empty disables registration |
| `SMS_ENABLED` | `false` unless SMS credentials, recipient preferences and delivery are separately qualified |

Host-only HttpOnly cookies are `Secure` in production, `SameSite=Lax` and scoped to the application path through `/api`. Qualify login, refresh, logout and both role cookies on the actual HTTPS hostname. A localhost test cannot verify Secure cookie transport through a hosted proxy.

`scripts/deploy-qualify.sh --api <HTTPS API> --app <HTTPS app> --expect-hsts` performs anonymous routing/origin/health checks. For a controlled owner fixture, supply `--owner-email` and inject `QUALIFY_OWNER_PASSWORD` privately; the authenticated phase uses the app's `/api` path for login, refresh and logout. It does not trigger or wipe a vault. This script is only one qualification component and has not been run against a hosted deployment here.

## Migration and sole sender

1. Capture artifact/commit identifiers, sanitized data inventory and a tested encrypted backup plus separate configuration/key inventory. Preserve release and delivery evidence.
2. Stop the legacy checker/sender. Put both new processes in release hold; restore operations also disable delivery entirely. Confirm only the selected sender can contact the provider.
3. Let the API release job alone run `alembic upgrade head` through `0008_delivery_attempts`. App startup does not migrate in production. Deploy the worker only after migration succeeds.
4. Review legacy wrapping/envelope anomalies without overwriting encrypted bytes. `LEGACY` means compatible historical material, not demonstrated readiness. Existing recorded check-ins backfill arming; empty vaults remain uninitialized.
5. Under hold run `python ops.py --adopt-legacy-release-evidence`. Previously released vaults get reconciliation evidence and dead-letter jobs; the tool never resends old notices. Review old provider IDs and timestamps before any operator-approved new notification.
6. Record the deployed hold with `python ops.py --record-hold`. Prove checker/delivery checkpoints, exact origin/proxy/Host rules, nonce hydration/navigation and redaction at application/platform sinks.
7. Enable delivery deliberately, run controlled registration, invitation, fresh beneficiary sign-in and release/recovery journeys with real email. Remove release hold only after evidence review; record the resulting hold configuration again.

Migrations 0006–0008 preserve encrypted bytes and reject destructive downgrades. A pre-remediation application is not an automatic rollback target: it can ignore holds and lack the new transaction/session contracts. On regression, restore the hold, stop sending, retain expanded schema and use a compatible reviewed application or forward repair. Never restore a database under an old authentication epoch.

## Monitoring and release gates

`/health` proves process liveness; `/readyz` proves database connectivity. Restricted `/operations/recovery` distinguishes stale/error checkpoints, release holds, overdue jobs, expired leases, dead letters, pending-release lag and recent provider attempt outcomes. Recovery degradation must alert without taking owner check-in routes offline. Configure monitor authorization privately and verify an actual alert recipient; configuration documents are not evidence that alerts are wired.

The CI workflow runs SQLite/PostgreSQL suites, production browser journeys, dependency/quality gates and image asset checks. Qualify the Northflank services, secret access, Vercel HTTPS `/api` routing, Supabase session behavior, real providers, recovery alerts, offsite restore and an independent cryptographic review before production activation. Load-test the expected inventory to establish capacity and measured processing budget. Proposed RPO 15 minutes/RTO four hours remain targets until a timed offsite restore demonstrates them.
