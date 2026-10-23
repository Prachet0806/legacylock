# LegacyLock — Production Readiness Remediation Plan

**Status:** Draft; production activation **NOT APPROVED**  
**Revised:** 23 October 2026  
**Proposed hosting:** Northflank Sandbox (API and worker), Vercel Hobby (Next.js), Supabase Free (PostgreSQL), Resend Free (email), UptimeRobot Free (public uptime checks)  
**Dependency review:** The former `braces` advisory was [withdrawn on 23 October 2026](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm); the frontend audit gate now permits no advisory exceptions. Recheck on the final release commit.

## 1. Decision and deployment boundary

The proposed request path is browser → Vercel HTTPS application origin → same-origin `/api/*` rewrite → Northflank FastAPI service → Supabase PostgreSQL. A **separate, continuously running** Northflank service runs `python worker.py` for checker passes and delivery. Resend handles transactional email. UptimeRobot checks public liveness, database readiness and the rewrite every five minutes; a separate authenticated, faster alert path checks recovery state. UptimeRobot pings are **not** a keep-awake mechanism for Northflank.

Keep `RELEASE_HOLD=true` and `DELIVERY_ENABLED=false` on both API and worker until the release checklist is signed by a named operator and an independent security reviewer. Do not start a real sender, lift the hold, or claim a production RPO/RTO from local tests. A hosted fixture under hold is necessary to collect evidence before activation.

**Eligibility gate:** Vercel Hobby permits personal, non-commercial use. If LegacyLock is a commercial product, paid work, or otherwise outside that scope, Vercel Hobby is not an approved production frontend. Select and qualify an eligible frontend plan/provider before activation. Northflank Sandbox is an always-on free sandbox with two service slots and limited resources, without a production SLA. Verify account eligibility, exact service/job limits, capacity, support expectations and costs in the intended accounts. If the required reliability cannot be demonstrated, upgrade the affected component or stop the release; do not treat a free-plan label as operational evidence.

Sources checked on 23 October 2026: [Northflank pricing](https://northflank.com/pricing), [Vercel Hobby terms](https://vercel.com/legal/terms), [Supabase backups](https://supabase.com/docs/guides/platform/backups), [Supabase Free project pausing](https://supabase.com/docs/guides/platform/free-project-pausing), [Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres), [Resend pricing](https://resend.com/pricing), [UptimeRobot Free limits](https://help.uptimerobot.com/en/articles/11604710-who-should-use-uptimerobot-s-free-plan).

## 2. Evidence baseline and corrections to the 19 October draft

The **19 October local** run reported SQLite backend `196 passed, 2 skipped`, a passing quality ratchet with **1,582 tracked diagnostics**, no advisories in the audited locked backend profile, and passing frontend lint/typecheck/audit/build under a temporary `braces` exception. That advisory was withdrawn on 23 October and the exception was removed; the current frontend audit reports zero vulnerabilities. The **12 October implementation record** reported a separate PostgreSQL 17 test run (`198 passed`) and browser-suite evidence. Neither record proves that hosted CI, the production containers, Northflank, Vercel, Supabase or real email have been qualified. Re-run the checks against the final reviewed commit and capture CI artifacts; do not describe unobserved hosted CI as passing.

The repository still contains a **Render-specific** `render.yaml` and `DEPLOY.md`. `frontend/vercel.json` has `https://api.example.com` as its `/api` destination, while `frontend/next.config.mjs` also defines an `API_UPSTREAM` rewrite. These are migration work, not completed deployment configuration. The backend Dockerfile currently installs `requirements.txt`, not the reviewed lockfile. The current production design uses the backend Docker image on Northflank and a native Next.js build on Vercel; a frontend Docker image is optional diagnostic evidence, not a Vercel launch requirement.

Supabase Free has **no automatic daily backup or PITR**. It can pause after low activity. The former phrase “managed encrypted restore” and the proposed **15-minute RPO / 4-hour RTO** are therefore unproven and cannot be checked off until an independent offsite backup/restore system and a timed drill establish them. Public five-minute uptime checks cannot prove a five-minute worker-lag alert.

### Credential and access inventory (prepare before creating services)

| Account or secret | Scope and handling |
|---|---|
| Source repository and DNS/domain | Operator access to the reviewed commit, intended app/API domains and DNS records; keep a separate controlled fixture domain. |
| Northflank | Project/service/job access for the operator; private runtime variables for API and worker. Verify actual account quota before binding production domains. |
| Supabase | Project admin for provisioning/restore and a restricted application database role; obtain the **actual** session/direct URLs and TLS CA. Keep database password and backup-runner credential out of frontend and logs. |
| Vercel | Project access, `frontend/` root, intended domains and nonsecret build values such as `NEXT_PUBLIC_API_URL=/api`; verify eligible plan. Do not put database, JWT, Resend or operations credentials in `NEXT_PUBLIC_*`. |
| JWT and sessions | API-only matching RSA PEM pair at configured `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`; separate `SESSION_SECRET`; synchronized fresh `AUTH_EPOCH` on API and worker. Escrow and rotate outside the repository. |
| Delivery encryption | Shared `DELIVERY_PAYLOAD_KEY`, `DELIVERY_PAYLOAD_KEY_ID` and retained `DELIVERY_PAYLOAD_KEYS` ring as required by live payloads; escrow keys separately from database backups. |
| Resend | Verified sending domain, `RESEND_API_KEY` and `NOTIFICATION_EMAIL_FROM` on API/worker as needed; controlled inboxes for delivery tests. |
| Monitoring and enrollment | Private `OPERATIONS_TOKEN` only in the authenticated monitor; `REGISTRATION_INVITE_CODE` only if enrollment is deliberately enabled. Never put secrets in UptimeRobot URLs or public probes. |
| Backup storage and alerts | Offsite storage, encryption/escrow and backup-runner credentials plus a separate alert channel with an operator and backup contact. |

Set the shared production flags and origins deliberately: `ENVIRONMENT=production`, `BACKGROUND_IN_API=false`, `HEARTBEAT_ENABLED=true`, `RELEASE_HOLD=true`, `DELIVERY_ENABLED=false`, `SMS_ENABLED=false`, exact `ALLOWED_ORIGINS`/`FRONTEND_URL`, actual `ALLOWED_HOSTS` and verified `TRUSTED_PROXIES`. Record which process receives each secret; do not blindly copy all secrets into both services.

## 3. P0 release blockers

### P0-1. Assign ownership and decide whether the free stack is eligible

**Owner:** Engineering lead and proposed production operator. **Due:** Immediately.

1. Name the operator, incident backup and independent security reviewer. Identify who controls DNS, domain verification, backups, secrets and release approval. Record the intended **personal/non-commercial or commercial** use and confirm Vercel plan eligibility in writing.
2. In the intended accounts, confirm Northflank Sandbox has two continuously running service slots and an available one-off job slot; verify memory/CPU, build, restart, region, network, log-retention and limit behavior using a small controlled pilot. Confirm Vercel, Supabase, Resend and UptimeRobot quotas and alert destinations. Reserve capacity for both API and worker; do not combine them to save a slot.
3. Set an admission limit for vaults/recipients/messages and budget. If Northflank capacity, Vercel terms or the required recovery objectives fail, decide on a paid tier or different approved host before deploying real user data.

**Acceptance:** Named owners, eligibility decision, account/quota evidence and an approved cost/capacity envelope. No silent waiver of an incompatible service term or failed reliability objective.

### P0-2. Independent cryptographic and recovery review

**Owner:** Engineering lead plus an independent cryptographer/security reviewer.

Review custom Shamir GF(256) arithmetic, malformed/duplicate shares, quorum boundaries, checksums versus adversarial authenticity, v1 AES-KW/AES-GCM envelope bounds, PBKDF2 parameters, legacy share handling, generation monotonicity and A→B→A reuse. Decide and document AAD coverage for vault, message, labels and categories. Deliver a threat model, known-answer/property tests, a written finding list and retest evidence for required fixes.

**Acceptance:** Independent sign-off on the implemented behavior. A generation counter alone does **not** revoke an old share. If the product promises revocation, implement and test actual re-encryption/rotation that makes old shares unable to decrypt migrated messages; otherwise explicitly constrain the production promise and have the reviewer accept that limitation. Keep full VMK rotation (E01) deferred only if the narrower release promise is approved.

### P0-3. Rework and qualify the actual hosting configuration

**Owner:** Platform/backend/frontend engineers. **Dependency:** P0-1 eligibility.

1. Replace the Render topology in `DEPLOY.md`; mark `render.yaml` unused for this deployment. Configure **Northflank API** from `backend/Dockerfile`, one instance/one Uvicorn worker, port **8000**, `--no-proxy-headers`, public HTTPS, `/health` liveness and `/readyz` database readiness. Build and run the reviewed backend image. Verify cold start, restart, secure logs and health checks.
2. Configure a **second Northflank service** from the same reviewed backend artifact with command `python worker.py`, no public listener, continuous operation and independent restart/health evidence. Set `BACKGROUND_IN_API=false` on API. Validate checker/delivery checkpoints after stop/restart and confirm exactly one delivery worker/provider sender.
3. Store environment secrets in Northflank. Mount the API JWT private/public PEM files at configured absolute paths and prove that the image's non-root `appuser` can read them at runtime; Northflank-injected files are root-owned. Keep PEMs and database credentials out of Vercel/browser bundles, images, repo, build logs and URL parameters. Worker does not need JWT files. Record rotation and emergency-revocation steps.
4. Configure Vercel with `frontend/` as root, locked `npm ci`, supported Node version and `npm run build`. Make **one authoritative** `/api/:path*` rewrite to the Northflank HTTPS API. Resolve the existing `vercel.json`/`next.config.mjs` duplication; remove all example origins. Keep `NEXT_PUBLIC_API_URL=/api`, and prove that preview builds cannot reach production API, cookies or data. Validate `/api/health`, JS/CSS assets, nonce/CSP hydration, HSTS and `Referrer-Policy` on the deployed app.
5. Set `ALLOWED_ORIGINS`/`FRONTEND_URL` to the exact app HTTPS origin; `ALLOWED_HOSTS` to actual backend/rewrite hosts; and `TRUSTED_PROXIES` only to verified direct-peer/forwarding CIDRs. Test browser login, refresh, logout, owner/beneficiary cookies, CSRF/origin failures and HTTPS `Secure` cookie behavior through the **Vercel** origin. Do not infer it from localhost.
6. Use a controlled one-off Northflank job from the same backend image for `alembic upgrade head` through `0008_delivery_attempts` **before** starting the new worker. No production startup migration. Pin/review deployment commits and disable or gate independent automatic promotion of API and worker until migration and sender cutover are coordinated. Prove a compatible forward-fix/hold rollback path; do not run destructive downgrades.
7. Run `scripts/deploy-qualify.sh --api <HTTPS API> --app <HTTPS app> --expect-hsts` against a disposable hosted fixture, including `--owner-email` and privately supplied `QUALIFY_OWNER_PASSWORD`. Capture results plus direct container/hosted tests of startup, assets and cookies. Redact secret-bearing output.

**Acceptance:** Two isolated services, reviewed build, working secret mounts, one migration path and sender, exact routing/security headers, hosted qualification and documented rollback. `render blueprints validate` is irrelevant to this topology.

### P0-4. Qualify Supabase Free PostgreSQL and connection limits

**Owner:** Backend/platform engineer. **Dependency:** P0-1.

1. Provision an isolated Supabase project and record region, database version, limits and project owner. Use the dashboard's exact connection strings. For an IPv4-only Northflank runtime, try the **session pooler on port 5432**; use direct IPv6 when supported. Do not substitute the transaction pooler on 6543 without proving application/session and migration compatibility. Use TLS, ideally certificate-verified `sslmode=verify-full`, and enforce SSL server-side after testing.
2. Restrict/disable unused Supabase Data APIs so the application database is reached only through its intended FastAPI contract; review database roles/privileges. Test connection loss/retry, row locks, migrations and worker concurrency on the actual service path.
3. Bound API and worker SQLAlchemy connection pools against the Free project's connection ceiling. Fix and test Alembic handling of percent-encoded reserved characters in `DATABASE_URL`; avoid logging URLs or errors containing credentials. Measure memory, Argon2 latency, database growth and connection count under the intended admission limit.
4. Exercise a Supabase pause/warning scenario or document a supported simulation and recovery runbook. Monitor pause notices and database readiness. A Northflank/UptimeRobot ping is **not a guarantee** against database pausing; if unattended recovery is essential, move to a plan that cannot auto-pause.

**Acceptance:** Actual hosted DB integration and load evidence, safe TLS/credentials, bounded connections and an explicit pause-risk decision.

### P0-5. Build offsite encrypted backups and prove recovery objectives

**Owner:** Reliability engineer plus production operator. **Dependency:** P0-4.

1. Implement a scheduled **offsite** logical backup for Supabase Free with separate encryption/key escrow, integrity verification, retention, failed-run alerting and access controls. Qualify a direct connection for `pg_dump`/restore from the backup runner; Supabase recommends direct connections for native backup operations. Do not count a database-local snapshot or an untested manual export as a resilient backup. Record backup schedule and data-change frequency against the desired RPO.
2. Restore onto a **separate** Supabase project/database with separate configuration/key inventory. Compare sanitized counts, crypto digests and Alembic head. Run `python ops.py --quarantine-restored --ack-isolated-restore --previous-auth-epoch <previous>`; verify that missing hold, disabled delivery or a fresh auth epoch is rejected.
3. In a fresh browser, prove owner login/decryption, beneficiary magic-link sign-in and reconstruction with independently held original shares. Measure backup age, detection, provisioning, key retrieval, restore, verification, reconciling and restart. Test a corrupt or missing backup and missing-key alert.
4. Record measured RPO/RTO and update `DEPLOY.md`. Keep the 15-minute/4-hour numbers as **proposed targets only**. If Free-tier backup cadence, pause risk or observed timing cannot meet accepted recovery objectives, change the service tier/design or obtain a documented, informed lower recovery promise before activation.

**Acceptance:** Repeatable encrypted offsite restore, independently retrievable keys, measured objectives and owner/reviewer approval of any residual loss/downtime.

### P0-6. Real Resend delivery pilot and quota budget

**Owner:** Delivery engineer. **Dependencies:** P0-3 secrets/hosted fixture.

Verify a sender domain and SPF/DKIM/DMARC; keep `RESEND_API_KEY` and `NOTIFICATION_EMAIL_FROM` in Northflank secret storage. On controlled recipients, trigger invitation, verification, beneficiary magic-link, release notification and grace warning. Capture provider acceptance **and independent inbox receipt**. Exercise stable job UUID/idempotency, duplicate suppression, retry/backoff, 23-hour reconciliation, invalid credentials, quota exhaustion and dead-letter handling. Free pricing currently advertises **100 emails/day and 3,000/month**; calculate worst-case recovery/grace/registration volume and alert before quotas bind. Keep `SMS_ENABLED=false` until separately qualified. Document provider incidents and manual reconciliation, without exposing tokens or recipient data in alerts.

**Acceptance:** Evidence of each end-to-end journey, failure behavior, quota headroom and one active sender.

### P0-7. Independent recovery monitoring with actual alert receipt

**Owner:** SRE/operator. **Dependencies:** P0-3 to P0-6.

Configure UptimeRobot Free five-minute checks for Northflank `/health`, `/readyz`, Vercel `/` and Vercel `/api/health`; validate current account limits and actual notification receipt. Configure **another qualified authenticated monitor** for `/operations/recovery` using `OPERATIONS_TOKEN` in a private header and a cadence that can detect/check a >5-minute stale checkpoint without an avoidable extra five-minute blind spot. Never place the token in a URL. Alert separately for worker checkpoint failure, due-work lag, expired leases, dead letters, pending-release lag, provider failures and **backup job failure/freshness**. Keep `/readyz` independent of worker failure so owner check-in routes remain available. Exercise stopped worker, bad provider credentials/quota, dead letter, hold degradation, failed backup and Supabase unavailable; record on-call receipt and escalation.

**Acceptance:** Alert delivery and timing measured from fault injection, named on-call and backup escalation. A configured monitor with no received alert does not pass.

### P0-8. Release data inventory, dependency audits and cutover

**Owner:** Operator, security reviewer and frontend/backend engineers.

Capture a sanitized `python ops.py` inventory from the intended database and investigate anomalies. With `RELEASE_HOLD=true`, `DELIVERY_ENABLED=false` and a fresh synchronized `AUTH_EPOCH`, stop any legacy checker/sender; take the tested backup; run the one-off migration; assess historical release evidence using `python ops.py --adopt-legacy-release-evidence`; record the hold with `python ops.py --record-hold`. Do not resend old notices automatically.

The former `braces` exception is closed following withdrawal of GHSA-vfj7-8cjw-p6xm; no dependency upgrade is required solely for that withdrawn advisory. Re-run `npm run audit`, `npm audit --omit=dev --audit-level=high`, Linux locked backend audit, lint, typecheck and final build. Align Docker and hosted CI with `requirements.lock.txt` and preserve the diagnostic ratchet. Any new advisory requires its own review and resolution before activation.

**Acceptance:** Reconciled inventory, single sender, migration evidence and passing audits of locked dependencies.

## 4. P1 hardening and explicit deferrals

Complete before activation where practical; every deferral needs an owner, date, risk statement and operator/reviewer acceptance. **P1 may not absorb a failed P0.**

| Workstream | Targeted work and acceptance |
|---|---|
| Shared rate limiting | Deploy one API instance/one Uvicorn worker while buckets are process-local. Before replicas or rolling overlap where enforcement matters, add a shared store/edge limit; verify trusted proxy CIDRs and client-IP attribution. |
| Audit evidence | Define required mutation/audit events, atomicity, retention and administrative access. Prove transaction rollback removes both mutation and audit. |
| Capacity | Load test expected vault, recipient and message counts on the actual free services; document p95 latency, Argon2 cost, memory, DB connections, checker and outbox lag; enforce admission limits. |
| Quality backlog | Keep the no-new-diagnostics ratchet; prioritize security-sensitive auth, crypto, trigger and delivery paths while reducing the 1,582-item backlog. |
| CSP | Inventory inline style needs and remove `style-src 'unsafe-inline'` if possible; test production hydration/decryption, blocked injected script and caching impact. |
| Notification provider guard | Reject a mock provider in production except an explicitly isolated drill fixture. |

Deferred product extensions remain E01 full VMK rotation (subject to the P0-2 release promise), E02 authenticated metadata format, E03 additional beneficiary credentials, E04 multi-replica capacity and E05 broad product cleanup. None is represented as implemented by this plan.

## 5. Sequence and dates

| Window | Deliverable |
|---|---|
| **23–25 Oct** | Name operator/reviewer; decide Vercel Hobby eligibility and free-tier reliability promise; start crypto review; inventory current data. |
| **26 Oct–1 Nov** | Replace Render deployment contract; align lockfile; provision isolated Supabase/Northflank/Vercel fixture and secrets; prove API+worker and DB connections. |
| **2–8 Nov** | Hosted browser qualification; Resend pilot; monitoring fault exercises; backup automation and first isolated restore. |
| **9–11 Nov** | Complete crypto findings and retest; measure RPO/RTO and quota/capacity. |
| **12–22 Nov** | Rehearse migration/cutover, finish P0 evidence and P1 decisions; independent operator/reviewer evidence review. |
| **After sign-off only** | Activate production deliberately, observe worker/delivery/backup/DB status, and retain the hold rollback path. No calendar date alone authorizes release. |

## 6. Production activation checklist

- [ ] Named operator/on-call and independent reviewer; intended use compatible with frontend plan; Northflank/Supabase/Resend/monitor quotas and reliability risks accepted.
- [ ] Independent crypto review completed; required fixes merged/retested; revocation claim matches actual behavior.
- [ ] Render references replaced in active deployment contract; Northflank API and independent continuous worker qualified; only one sender; non-root JWT file access and secret rotation proved.
- [ ] Vercel native build and one same-origin `/api` rewrite qualified on HTTPS; production and preview isolated; cookies, CSP, assets, HSTS and origin/proxy/host rules tested.
- [ ] Supabase TLS, session/direct endpoint, bounded connection pools, role/API surface and migration compatibility proved; pause risk accepted or removed by tier change.
- [ ] One-off migration through `0008_delivery_attempts` rehearsed with old sender stopped, backup taken, hold active and destructive downgrade prohibited.
- [ ] Automated offsite encrypted backup, separate key escrow and isolated fresh-browser restore passed; measured RPO/RTO documented and accepted.
- [ ] Controlled Resend inbox delivery and failure/idempotency/quota tests passed; SMS disabled; no mock provider in production.
- [ ] Public five-minute uptime monitors and faster private recovery/backup alerts configured; fault-injection receipt and on-call escalation recorded.
- [ ] Final-commit hosted CI, PostgreSQL tests, browser journeys, Linux dependency audits, lockfile install, backend container and Vercel production build passed; no unreviewed dependency advisories.
- [ ] Sanitized `ops.py` inventory reconciled; `--record-hold` run; exact production secrets/configuration verified with `ENVIRONMENT=production`, fresh shared `AUTH_EPOCH`, `RELEASE_HOLD=true`, `DELIVERY_ENABLED=false`.
- [ ] Operator and independent reviewer approve the evidence **in writing**.

**Activation:** With these boxes checked, deliberately enable delivery and lift the hold in the reviewed order for the application's release contract; record the resulting hold state again using `python ops.py --record-hold`. Immediately watch recovery checkpoints, outbox lag, provider outcomes, DB readiness, backup freshness and incident alerts. On regression, restore hold, disable sending, keep the expanded schema, preserve evidence and deploy a compatible forward fix; never revert to a pre-remediation app or an old `AUTH_EPOCH`.

## 7. Risk register

| Risk | Consequence | Gate / response |
|---|---|---|
| Vercel Hobby used for commercial deployment | Terms/continuity failure | P0-1 eligibility decision; use an eligible paid/alternate frontend if commercial. |
| Supabase Free pause or missing managed backups | Recovery unavailable or data loss | P0-4 pause response; P0-5 independent offsite backups and measured restore; upgrade if objectives cannot be met. |
| Northflank Sandbox resource/support limits | API/worker restart or lag | Two-service hosted load/restart test, admission limits, alerting and tier decision. |
| Northflank root-owned secret mount unreadable to `appuser` | API startup failure | Verify JWT mount/readability with actual image before release. |
| Competing rewrite definitions or preview→production route | Cookie/auth break or data leak | One authoritative `/api` route and isolated preview E2E test. |
| Custom Shamir/envelope flaw or false revocation claim | Confidentiality/recovery failure | Independent review, required fixes and honest release promise. |
| Provider accepted but email absent; Resend quota exhausted | Beneficiary lockout or late notice | Inbox pilot, quota model, dead-letter alert and reconciliation. |
| Five-minute public probes miss worker failure | Silent recovery degradation | Faster authenticated recovery alert and fault-injection proof. |
| Lockfile drift, new dependency advisories or hidden diagnostics | Unreviewed build | Locked Linux audits and quality ratchet. |

**Immediate next action:** assign operator/reviewer and settle Vercel Hobby eligibility, then migrate the Render deployment contract into a reviewed Northflank/Vercel/Supabase configuration while the independent crypto review proceeds.
