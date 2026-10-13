# LegacyLock deployment contract

Production activation is gated by [the implementation record](docs/remediation-implementation.md), [operations runbook](docs/remediation-operations.md) and [dependency exceptions](docs/dependency-exceptions.md). Local tests do not establish real email delivery, HTTPS cookie behavior, managed backup objectives, capacity or independent cryptographic review.

## Topology and artifact

Browser → HTTPS application origin → same-origin `/api/*` rewrite → FastAPI → PostgreSQL 17. A separate recovery worker owns checker passes and delivery attempts. Keep one API instance while rate limits use process-local buckets. Rolling replacement also needs edge enforcement if the limit must span old/new instances. Never trust arbitrary forwarded headers to improve client-IP attribution.

Build immutable frontend/backend images from the reviewed tree. Targets are Python 3.12.14 and Node 22.23.3; install locked dependencies. The frontend builder consumes `NEXT_PUBLIC_API_URL=/api` and `API_UPSTREAM=<backend origin>` and the runner serves `server.js` with `.next/static` colocated. Rewrite destinations are build inputs. On Vercel replace the example destination in `frontend/vercel.json`; keep `/api` and `Referrer-Policy: no-referrer`.

`render.yaml` contains an API web service, independent worker and managed PostgreSQL. Replace example domains, fill secret-store settings, mount JWT files in the dashboard and run `render blueprints validate render.yaml` against the intended Render account/CLI before creation. YAML parsing alone does not validate platform schema or secret mounts. Auto deployment is disabled for coordinated migration and sender cutover.

## Required configuration

| Setting | Contract |
|---|---|
| `ENVIRONMENT` | `production` on API and worker |
| `DATABASE_URL` | Intended PostgreSQL URL with platform-required TLS; backed up and isolated from test databases |
| `SESSION_SECRET` | Dedicated random value, at least 32 characters |
| `AUTH_EPOCH` | Deployment-wide identifier, synchronized on API/worker; replace after restoration |
| JWT files | Corresponding RSA private/public PEM pair, at least 2048 bits. API validates correspondence at startup. Render paths: `/etc/secrets/jwt_private.pem` and `/etc/secrets/jwt_public.pem`. Worker needs neither file |
| `DELIVERY_PAYLOAD_KEY` | Separate random 32-byte base64 AES-GCM key, backed up outside the database |
| `DELIVERY_PAYLOAD_KEY_ID`, `DELIVERY_PAYLOAD_KEYS` | Current version and secret JSON ring of retained older versions; do not retire a version with live/retained payloads |
| `ALLOWED_ORIGINS`, `FRONTEND_URL` | Exact application HTTPS origin; no wildcard or `null` |
| `ALLOWED_HOSTS` | Actual API hostnames, including platform health/rewrite host |
| `TRUSTED_PROXIES` | Verified direct-peer and forwarding-chain CIDRs only. Start Uvicorn with `--no-proxy-headers`; the application owns trust parsing |
| `BACKGROUND_IN_API` | `false` with the separate worker |
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

The CI workflow runs SQLite/PostgreSQL suites, production browser journeys, dependency/quality gates and image asset checks. Qualify actual built images, Render Blueprint, secret mounts, HTTPS `/api` routing, real providers, recovery alerts, managed restore and an independent cryptographic review before production activation. Load-test the expected inventory to establish capacity and measured processing budget. Proposed RPO 15 minutes/RTO four hours remain targets until a managed restore demonstrates them.
