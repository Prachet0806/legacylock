# LegacyLock: local audit and deployment roadmap

**Database decision updated 5 November 2026:** the deployment target is a new, empty Neon PostgreSQL database. Supabase references below describe the 3 November audit and are superseded for the active setup by [DEPLOY.md](../DEPLOY.md). No Neon connection, migration, backup, or hosted qualification has been verified here.

**Audit date:** 3 November 2026  
**Scope:** current `unstable` checkout at `fa41713`, including eight uncommitted frontend changes. This is a local code, configuration, documentation, and test audit. No production account, hosted deployment, provider delivery, or real-data restore was verified.  
**Decision at audit:** **not ready to accept real user data or activate recovery delivery**. The worker health-check and migration-documentation blockers below were addressed later on 3 November. The dependency gate now has a narrow development-only advisory exception that requires independent review before release. Hosted qualification and external review remain open.

**Launch classification confirmed by the owner:** real user data, non-commercial. Treat this as production operation. Render's free tier is limited to synthetic qualification; select a production-appropriate host or tier before accepting real data. Vercel Hobby's non-commercial condition may fit, subject to its actual account terms and reliability needs.

## 1. System and trust boundaries

```
Browser (owner/beneficiary; vault crypto and shares stay here)
    -> Vercel HTTPS app -> same-origin /api rewrite
    -> Render FastAPI -> PostgreSQL
                         -> transactional delivery jobs
    -> separate Render worker -> Resend
    -> restricted /operations/recovery monitor and offsite backup runner
```

The repository is primarily a FastAPI backend with a Next.js client and an independent checker/delivery worker. The security-sensitive paths are:

1. **Enrollment and session:** browser registration/login calls `frontend/lib/api/transport.ts` through `/api`; `backend/routers/auth.py` verifies identity and `backend/services/cookies.py` sets host-only HttpOnly cookies. The Next rewrite, production origin/host configuration, and actual HTTPS proxy determine whether this works safely.
2. **Vault release:** `backend/routers/trigger.py` or `backend/services/heartbeat_checker.py` reaches `backend/services/trigger_service.py`; `backend/services/recovery_readiness.py` requires initialized material, a finalized current ceremony, quorum assignments, and a current owner-reported drill. A release creates outbox intent; `backend/services/outbox.py` leases jobs and records provider attempts. `RELEASE_HOLD` and `DELIVERY_ENABLED` must be coordinated on API and worker.
3. **Beneficiary recovery:** access is gated on the backend, while `frontend/app/recovery/page.tsx` reconstructs shares and decrypts in the browser. The owner-reported drill is a release gate, but does not independently prove that a beneficiary possesses shares. `frontend/tests/crypto.spec.ts` explicitly confirms that resharing does not cryptographically revoke an old quorum.
4. **Operations:** `/health` is liveness, `/readyz` checks the database, and authenticated `/operations/recovery` reports worker checkpoints, hold, backlog, expired leases, and dead jobs. An external monitor and a tested backup runner are necessary; neither is configured by this repository alone.

Key shared-fate groups: the API and worker share the schema, delivery key ring, hold flags, and auth epoch; the frontend and API share the `/api` rewrite, cookie, origin, and host contracts; database recovery also requires separately escrowed secrets and original recovery shares. The application rate limiter is process-local, so scaling API instances changes its effective protection.

## 2. Local evidence

| Check | Result on this checkout | Limit |
|---|---|---|
| Git | `unstable` matches `origin/unstable` at `fa41713`; eight modified frontend files, no untracked files before this report | Redesign is not in a reviewed commit/hosted CI run |
| Backend tests | `215 passed, 2 skipped` with Python 3.12.14 | Skips are PostgreSQL-only row-lock cases; this run used the local SQLite test mode |
| Backend quality gate | Passed, with **1,551 existing tracked diagnostics** | A nonregression ratchet, not a clean lint/type baseline |
| Frontend | Typecheck, `next lint`, production `next build`, and 20 standalone crypto tests passed | Local Node is 22.19.0; CI/target is 22.23.3. Authenticated production-browser suite was not run locally |
| Dependencies | Raw frontend audit reports 20 affected development-tool packages from one `minimatch` advisory; the narrow gate exception accepts only that advisory when every affected lockfile path is development-only. Production-only npm audit reports zero. Locked backend `pip-audit` reported no known vulnerabilities | Independent reviewer must accept or replace the exception; rerun locked audits in CI |
| Image/host | Docker daemon unavailable locally | No local image, worker health, hosted TLS/cookie, database, email, alert, or restore proof |
| Diff hygiene | `git diff --check` passed | Git warned that `globals.css` line endings may change on a later checkout/write |

No production readiness claim follows from these local passes. The CI workflow includes PostgreSQL tests, browser journeys, and an isolated restore rehearsal; their current hosted result was not inspected here.

## 3. Findings, ordered by release impact

### P0 — hosting and recovery decisions

- **The proposed free stack is not a production approval.** [Render's free tier](https://render.com/docs) says it should not be used for production applications. [Vercel Hobby terms](https://vercel.com/legal/terms) restrict it to personal or non-commercial use. Determine whether this is a private synthetic pilot or a real commercial/user-data service; choose eligible tiers or another host before real data. Confirm account limits and expected spend in the actual accounts.
- **No verified recovery objective.** [Supabase's backup documentation](https://supabase.com/docs/guides/platform/backups) says automatic daily backups cover Pro, Team, and Enterprise, and recommends offsite exports for Free. The local `backend/restore_rehearsal.py` is deliberately a synthetic loopback PostgreSQL exercise. A scheduled encrypted offsite backup, separate key escrow, fresh-project restore, and measured data-loss/downtime are still required. The proposed 15-minute RPO and four-hour RTO in `DEPLOY.md` remain targets.
- **Independent cryptographic review is still required.** Custom browser Shamir and vault encryption are central to the product. Review share authenticity, generation/revocation semantics, key wrapping, ciphertext metadata binding, legacy material, and browser network boundaries. The current test suite confirms old quorum non-revocation; product language and release policy must accurately reflect that.

### P0 — code and deployment gate

- **Frontend audit — mitigated, review pending.** The raw audit reports one `minimatch` advisory propagated to 20 development-tool packages. A global `minimatch` 11.0.1 override made legacy `glob` throw and was removed. `frontend/scripts/audit.cjs` now accepts only that exact advisory when every affected lockfile path is development-only and the dependency graph reaches the reviewed root; any other advisory or path fails. Production-only npm audit is clean, and the original glob caller, lint, typecheck, crypto tests, and build pass locally. Independent security review must accept this narrow build-tool exposure or require a compatible tooling migration before real data.
- **Worker image health check — resolved locally.** The image no longer probes the API's `/readyz` endpoint, which a worker does not serve. CI now starts the worker from the production image and checks both durable worker checkpoints. The actual host still needs process supervision and a private checkpoint-freshness alert.
- **No deployment orchestration is checked in.** `.github/workflows/ci.yml` tests/builds but does not coordinate a one-off migration, API and worker promotion, release hold, or sender cutover. Pin the artifact to one reviewed commit and gate promotion so the migration finishes before the worker starts. Keep one sender and one API instance until process-local rate limits are replaced or enforced at the edge.
- **Migration documentation — resolved locally.** `DEPLOY.md` and the older planning draft now name `0009_verified_recovery`, the actual head that clears unverified legacy share-generation claims. The older draft is marked historical; operators should use this roadmap and `DEPLOY.md`.

### P1 — hosted qualification and operating limits

- **Hosted trust boundaries are unproven.** Qualify the Vercel `/api` rewrite, isolated preview API, exact origins/hosts/proxy CIDRs, CSP/nonce hydration, Secure owner and beneficiary cookies, refresh/logout, and CSRF rejection on real HTTPS domains. Localhost does not exercise these.
- **Database and provider behavior are unproven.** Use the exact Supabase connection string and certificate. [Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres) recommends a direct connection for migrations and native backup tools; a persistent IPv4-only app can use session pooling. Prove row locking, migrations, connection limits, TLS verification, Resend accepted-versus-inbox delivery, quotas, retry/uncertain outcome, and dead-letter reconciliation.
- **Monitoring exists as code/docs, not as received alerts.** Configure public liveness/readiness/rewrite probes, a private token-header monitor for `/operations/recovery`, backup freshness/failure alerts, and named escalation. Exercise stopped worker, database outage, provider failure, dead letter, and failed backup; record actual receipt and timing. During a planned hold, `/operations/recovery` intentionally returns 503, so the alert plan needs a recorded maintenance/hold state.

## 4. Roadmap with acceptance gates

| Stage | Work and dependencies | Evidence needed to exit |
|---|---|---|
| **0. Decide launch class** | Name operator, backup, security reviewer, intended users/data, reliability promise, and budget. Pick eligible hosting plans; use free tiers only where their current terms and failure modes fit the pilot. | Written topology/plan decision and named owners; real-data release criteria agreed. |
| **1. Freeze a reviewed build** | Preserve the eight frontend edits and current blocker fixes. Review the single development-only `minimatch` advisory exception and diff. Run full CI on one commit, including PostgreSQL, browser, restore, locked dependency audits, and image jobs. | Green hosted CI tied to commit/image digests; no unexplained skips or unreviewed advisories; worker checkpoint test demonstrated. |
| **2. Build isolated hosted fixture** | Provision separate staging DB/API/worker/app and secret stores. Set `ENVIRONMENT=production`, `BACKGROUND_IN_API=false`, `HEARTBEAT_ENABLED=true`, `RELEASE_HOLD=true`, `DELIVERY_ENABLED=false`, `SMS_ENABLED=false`, fresh shared `AUTH_EPOCH`, exact hosts/origins, verified TLS, bounded DB pools, API-only JWT keys, shared delivery key ring. Use a one-off migration job at head before starting the worker. | Migration record at `0009_verified_recovery`; API `/health` and `/readyz`; worker checkpoints; no production data or cross-environment preview route. |
| **3. Prove complete journeys** | On synthetic identities, run `scripts/deploy-qualify.sh` plus browser registration, verification, owner setup, ceremony, accepted beneficiary invitation, owner drill, check-in, controlled release, beneficiary login/reconstruction, and logout. Enable delivery while release hold stays active for controlled email tests; test release notification only in the disposable fixture. | HTTPS cookie/CSP/routing evidence; provider ID **and** inbox receipt; recovery plaintext verified in a fresh browser; failure and retry cases recorded. |
| **4. Prove operations and recovery** | Implement scheduled encrypted offsite backups and separate key escrow. Restore into a fresh isolated project under `RELEASE_HOLD=true`, `DELIVERY_ENABLED=false`, and rotated `AUTH_EPOCH`; reconcile inventory and decryption with original shares. Load test expected vault/message/recipient volume; inject monitor failures. Obtain independent crypto/security review and fix required findings. | Measured RPO/RTO and capacity, successful timed restore, alert receipt/escalation, reviewed cryptographic limits, and a rehearsed forward-fix/hold rollback. |
| **5. Controlled production cutover** | After sign-off, inventory and back up the intended database, stop any old checker/sender, migrate once to head, reconcile legacy release evidence, record hold, deploy pinned API and worker, verify one sender, then deliberately enable delivery and lift release hold in the agreed order. | Signed go/no-go record; exact artifact/config IDs; successful live synthetic canary; immediate observation of DB, worker, outbox, provider, backup, and alert state. |

**Rollback during cutover:** reinstate release hold, disable delivery, preserve outbox/audit evidence and the expanded schema, and use a compatible forward fix. Do not downgrade migration `0009` or revive an old authentication epoch.

## 5. Minimum launch record

Keep a single release record containing: source commit and image digests; plan and account eligibility; environment and secret inventory without secret values; migration revision; sanitized `ops.py` inventory; backup ID and timed restore evidence; hosted browser/crypto and email receipts; monitoring fault-injection results; capacity limit; independent review disposition; named approval; activation time; and a tested hold/rollback path. Recheck external plan terms and quotas at the release date.
