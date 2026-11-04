# LegacyLock Comprehensive Remediation Plan

Prepared 11 October 2026. Status: proposed engineering baseline. Scope: all 32 findings in the project critique, incorporating the corrections in the remediation plan review. Those historical source documents are not present in this checkout. Implementation and deployment are separate work; a task closes only when its acceptance evidence is recorded.

LegacyLock should reach a release where a valid check-in prevents stale automatic release, existing secrets survive every supported key operation, beneficiaries can authenticate long after enrollment without owner help, and every release creates recoverable delivery work. Preserve browser encryption and the current stack. Fix shared domain operations and transaction boundaries before adding features.

**1 Release scope and governing invariants**

The first qualified release includes safe initial setup, passphrase rewrapping, finalized recovery ceremonies, durable beneficiary reauthentication, atomic heartbeat/manual release, notification delivery with retries, revocable sessions, deployment hardening, accurate product status, and a verified restore procedure. Resharing may ship only after its replacement-ceremony tests pass. Full master-key rotation, a new authenticated-data format, additional sign-in methods, and broader scaling have separate gates in section 12.

Existing unsafe setup/rotation and production reset paths must be disabled server-side while replacements are unfinished. An unavailable safe automatic-release implementation results in a visible, monitored release hold, with owner check-ins still working. A hold requires reconciliation of overdue vaults before resuming. It is a containment measure, not completion of the recovery service.

| Invariant | Required behavior |
|---|---|
| I01 Browser confidentiality | Plaintext bodies, vault passphrases, unwrapped vault/message keys, and raw Shamir shares never reach the API, providers, logging, telemetry, or durable browser storage |
| I02 Atomic eligibility | All changes affecting release eligibility serialize through one authoritative vault-state revision and transaction contract |
| I03 Safe material updates | A complete wrapping bundle changes atomically under an expected material revision; initialized setup cannot replace it accidentally |
| I04 Honest recovery | Finalized policy, current assignments, recipient enrollment, owner acknowledgments, and drill evidence remain distinct |
| I05 Durable recipient access | Accepted, active beneficiaries can reauthenticate from a fresh browser after long inactivity without owner intervention |
| I06 Durable release intent | A successful release commits its state, audit event, business event, and intended delivery jobs together |
| I07 Recoverable delivery | Due retries and abandoned claims resume after failures; repeated business actions do not create duplicate events |
| I08 Principal separation | Every API authorization, session family, refresh operation, unlocked key, and asynchronous result is bound to its principal and vault |
| I09 No false revocation | Labels and client checks cannot revoke already learned keys, plaintext, or copied encrypted bundles |
| I10 Qualified operation | Production uses real mandatory providers, migrated schema, tested cookies/proxy paths, monitored workers, and demonstrated backup restoration |

Extend the existing [security requirements](legacylock-docs/15-security-requirements.md) with these contracts and remove duplicate/ambiguous invariant numbering during documentation reconciliation. Authentication password processing remains separate from the vault passphrase.

**2 Proposed decisions and implementation defaults**

These defaults make the backlog concrete. Record the selected alternatives before implementing dependent work; they are not previously approved product policies.

| Decision | Proposed baseline | Consequence and alternatives |
|---|---|---|
| D01 Beneficiary sign-in | Email-only, expiring single-use magic links for currently accepted and active beneficiary assignments; no mandatory password/passkey in this release | Mailbox control is the identity credential. Explicitly accept mailbox takeover/loss/address-recycling risk or choose password/passkey enrollment before M5. Cookie lifetime is not the recovery mechanism |
| D02 Interrupted shares | Restart an interrupted draft with fresh random shares and a fresh 32-character hexadecimal generation; clear its acknowledgments | No raw share persistence. The old finalized ceremony remains active. A protected portable draft can be a later capability |
| D03 Release permanence | Production release is terminal; check-in cannot undo disclosure. Initially make released vaults read-only for secret creation/editing and key changes, while preserving owner read/export/delete | Prevents accidental publication of new secrets. If post-release writes are chosen instead, require explicit disclosure UX and tests; never describe rearming as revoking previous access |
| D04 Cryptographic compatibility | Keep the existing version 1 WebCrypto format and current Shamir encoding; fix validation and lifecycle first | An algorithm/format change requires a separate version, migration, and independent review |
| D05 Reshare versus rotation | Reshare the same key only through a replacement ceremony; explain that old quorums still know the key. Disable full master-key rotation until E01 passes | Changing a generation is not cryptographic revocation |
| D06 Delivery contract | One durable business event; at-least-once delivery attempts; provider-assisted duplicate suppression where supported | Provider acceptance is not inbox delivery; do not promise exactly-once email/SMS |
| D07 Browser/API topology | Same-origin `/api` proxy for the first release; host-only HttpOnly cookies, Secure in production, SameSite=Lax | Arbitrary cross-site deployment is unsupported until separately qualified with its cookie/CSRF policy |
| D08 Warning recipients | Owner receives check-in reminders and cancellation information; beneficiaries receive accurate grace/release notices according to explicit channel preferences | No promise that LegacyLock will send a Shamir share |
| D09 Heartbeat timing | Explicit arming; deadlines derive from the last committed check-in. Grace starts at the missed deadline, not the observation time | Scheduler downtime does not silently extend deadlines. Overdue catch-up must respect holds and fresh state |
| D10 Required provider | Real email is mandatory for release and magic-link sign-in; SMS is optional and explicitly enabled per deployment/recipient | Missing enabled-channel credentials fail qualification; mock success is never accepted in production |

Initial sizing and operational targets are proposals to verify at M0/M7: checker cadence 60 seconds with a five-minute release-processing budget; page size 50, maximum 100; new secret body limit 1 MiB of UTF-8 plaintext, with the ciphertext/tag/base64 request limits derived accordingly. Read existing larger valid records without destructive truncation. Adopt provisional backup RPO of 15 minutes and RTO of four hours only after a restore drill demonstrates them; a `pg_dump` schedule alone does not establish that RPO.

**3 Responsibility and milestone dependencies**

Roles identify responsibilities, not assumed team size. Assign named owners at kickoff. The backend owner maintains transactions, migrations, sessions, and workers; the frontend owner maintains crypto lifecycle and browser flows; the platform owner maintains runtime, deployment, providers, monitoring, and recovery; the security reviewer checks threat boundaries; the test owner records evidence. One person can hold several roles, but security-critical changes need a second reviewer.

| Milestone | Outcome | Dependency | Lead |
|---|---|---|---|
| M0 | Reproducible baseline, data inventory, deployment contract | None | Platform and backend |
| M1 | Demonstrated failure paths contained | M0 baseline; use small targeted changes | Backend and frontend |
| M2 | Approved contracts and compatible schema foundation | M0; containment continues | Backend with security review |
| M3 | Atomic release, durable events, real delivery worker | M2; integrates M5 enrollment/auth email | Backend |
| M4 | Safe key material and ceremony lifecycle | M2; shares version contracts with M5 | Frontend and backend |
| M5 | Durable beneficiary sign-in and correct sessions | M2; delivery integration requires M3 | Backend and frontend |
| M6 | Patched and qualified deployment, browser defenses, bounded APIs, accurate product flows | Starts after M0; final integration needs M3–M5 | Platform and frontend |
| M7 | Evidence, restoration, controlled release, pilot | M3–M6 complete | Test and platform |

M3, M4, and M5 can progress independently after M2 defines their shared contracts. M6 dependency/build changes start early; do not leave E2E fixtures or observability until the end. Publish small working increments following the repository [development workflow](legacylock-docs/16-development-plan.md).

**4 Detailed implementation backlog**

**M0 Reproducible baseline and inventory**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M0.1 | Record reviewed commit plus working-tree changes without discarding existing work. Inventory vault states, check-ins, wrapping bundles, generations, assignments, invalid envelopes, oversized records, sessions, and notification statuses. Use aggregate/sanitized diagnostics | Versioned baseline and inventory; no plaintext, raw credentials, keys, or shares in output; existing data is accounted for |
| M0.2 | Recreate a working local Python environment from a declared supported interpreter. Resolve backend constraints through one lock workflow consumed by local/CI/container installs. Maintain fast SQLite tests and a distinct migrated PostgreSQL profile; set `USE_POSTGRES=1` when needed | Fresh install produces resolved versions; Alembic builds empty PostgreSQL schema; the test profile actually connects to PostgreSQL rather than silently falling back to SQLite |
| M0.3 | Choose D07 topology and record runtime/image/dependency versions, API prefix, proxy trust, cookie flags, keys, provider configuration, and migration ownership. Capture prior test results as baseline, not release evidence | One deployment contract and reproducible build inputs; current failures are tracked; qualification does not rely on test-mode `create_all` |

**M1 Contain demonstrated failures**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M1.1 | Reject initial setup/material replacement on initialized vaults in the backend; remove wrong-passphrase links to destructive setup. Gate unfinished rotation/reset actions in the UI and API | A second setup returns a conflict; the original message and wrapping bundle remain decryptable; direct API calls cannot bypass the guard |
| M1.2 | Replace the stale automatic predicate with a common locked status/check-in read and explicit eligibility guard; separate manual authorization. Increment the authoritative revision for every relevant check-in/config/arming change | Expired-grace interleaving commits a check-in before release eligibility is reacquired and remains active; independent PostgreSQL transactions test both orderings |
| M1.3 | Dispatch logout by role; revoke beneficiary sessions/challenges on contact replacement and deletion. Return accurate terminal-release/check-in responses | Old credentials fail subsequent authorization; owner and beneficiary logout clear the correct cookies; released vaults do not appear rearmed by a check-in |
| M1.4 | Add one refresh promise per role and session epoch; retry each original request once after refresh. Distinguish expired/missing session from invalid action password and revoked session | Parallel expired requests cause one refresh per tab; a wrong manual-trigger password displays an error without rotating/logging out a valid session |
| M1.5 | Reject mock mandatory providers in production; remove email bodies/credential links from mock and error logs; sanitize known credential-bearing paths | Production missing email credentials fails startup/qualification; a synthetic link secret does not appear in captured application logs |

M1 reduces exposure; it does not authorize production recovery until release/outbox, beneficiary authentication, migration, and qualification gates pass.

**M2 Domain contracts and schema foundation**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M2.1 | Resolve D01–D10; specify state transitions, lock order, transaction ownership, API error codes, revisions, delivery semantics, and restoration holds. Preserve independent invitation/share lifecycles | Short architecture decision records with examples and invariants; automatic and manual release share a commit path but retain distinct eligibility/authorization checks |
| M2.2 | Add compatible ceremony, assignment revision, session/challenge, business-event, delivery, and audit structures described in section 5. Expand existing constraints before using new states. Backfill existing armed/key/recovery state from evidence | Migration rehearsal on representative old rows; no key overwrite, accidental disarming, false readiness, or loss of old valid recovery |
| M2.3 | Define API schemas for complete encrypted bundles, `expected_revision`, idempotency keys, role/session errors, beneficiary waiting status, pagination, and nullable field clearing. Add client/server contract checks | One documented contract; rejected crypto updates leave the old object intact; conflicts and invalid input are distinguishable |

**M3 Atomic heartbeat release and delivery**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M3.1 | Implement one domain release operation over `VaultStatus`. Serialize all eligibility writers through its row; reread heartbeat state under the lock. Compute due active→grace and grace→release transitions, create episode IDs, inject one clock, and stage audit/events/jobs before the caller commits | Correct deadlines after downtime; no stale release; repeated manual/checker requests yield one business event; check-ins cancel the current episode's unsent warnings |
| M3.2 | Implement business-event and per-recipient/channel delivery tables with enforced unique keys, due indexes, recipient/contact revisions, provider IDs, accurate attempt timestamps, and protected credential payloads | A transition rollback removes its event/jobs/audit; all intended recipients/channels exist after commit; repeat actions cannot enqueue duplicates |
| M3.3 | Add a separate worker using bounded PostgreSQL claims, lease expiry, claim tokens, actual sends, due retries, jitter/backoff, maximum attempts, cancellation, and dead letters. Network calls occur outside the claim transaction | Worker death before/after send resumes work; stale workers cannot overwrite reclaimed results; fail/fail/succeed produces three real attempts; one failed channel does not block others |
| M3.4 | Implement typed provider results for accepted/transient/permanent/uncertain outcomes. Persist provider identifiers, idempotency keys, sanitized errors, and verified webhook results if delivery confirmation is used | Accepted is not reported as delivered without evidence; timeout ambiguity is tested; provider quota and credential failures alert; optional SMS never mock-succeeds |
| M3.5 | Replace stdout-only auditing at all sensitive mutations with the existing staged audit service. Cover contact/share/key/policy/config changes, check-ins, release, session revocation, and administrative holds | Each committed mutation has a sanitized durable audit; rollback removes both; request/system actor and correlation are accurate |

**M4 Safe crypto and recovery ceremonies**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M4.1 | Implement strict decoded version 1 envelope validation and bounded KDF policy; reject unsupported format/algorithm, inconsistent metadata, truncated key/IV/tag, and partial crypto updates. Preserve valid legacy reads and quarantine malformed records for repair | Current frontend encryption round-trips; missing IV and one-byte blobs fail before commit; corruption produces a specific error rather than a wrong-passphrase/setup suggestion |
| M4.2 | Implement draft/distribution/finalization/cancellation using one ceremony ID and immutable generation. Initial setup finalizes policy plus complete wrapped material atomically; replacement resharing keeps the existing key and active ceremony until cutover | Failure/reload at every step leaves either the prior finalized ceremony or a restartable inactive draft; new messages cannot be saved under unfinalized initial material |
| M4.3 | Implement passphrase rewrap using the same vault key, new salt, and complete wrapping bundle with expected material revision. Verify the prepared bundle locally before committing/adopting | New passphrase unlocks; old material is not used by the current client; all existing message keys/shares remain valid; stale competing updates return conflict |
| M4.4 | Bind the private crypto manager to principal, vault, material/ceremony revision, and session epoch. Clear owner/beneficiary plaintext, editor body, passphrase/share inputs and key references on lock/logout/identity change. Discard late async results | Cross-account/cross-tab session changes force unlock; locked plaintext is absent from UI/editor state; a delayed decrypt or save cannot repopulate or write under a new identity |
| M4.5 | Bind assignments and drill evidence to finalized ceremonies; enforce generation history and explicit legacy compatibility. Validate Shamir with vectors/properties/interoperability and independent focused review | Mixed, duplicate, corrupted, wrong-policy/generation shares fail for modern ceremonies; legacy migration remains recoverable; resharing is never represented as revocation |

**M5 Durable authentication and enrollment**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M5.1 | Implement D01 request/redeem endpoints for purpose-bound, expiring, hash-stored single-use challenges. Scope them to an active accepted beneficiary and contact revision; queue protected email payloads; use generic responses and per-IP/per-recipient cooldowns | A fresh browser after simulated years of inactivity authenticates without original invite/refresh cookie or owner action; expired/replayed/revoked/wrong-purpose challenges fail |
| M5.2 | Give owner/beneficiary sessions explicit independently revocable families and refresh history. Atomically rotate session state/refresh credentials; add real cross-tab exclusion with bounded fallback, and explicit replay handling | Parallel tabs, response reordering, multiple devices, logout and deliberate replay behave as specified; healthy concurrency does not revoke all sessions |
| M5.3 | Reenroll changed beneficiary contacts without silently changing the share generation. Invalidate old families/challenges/queued credential jobs, clear acceptance until verification, and expose authenticated pre-release waiting status without ciphertext | Previous recipient cannot authorize new requests after replacement; the new contact completes enrollment; pre-release beneficiaries see a truthful waiting page rather than a login loop |
| M5.4 | Make registration, verification redemption, invitation acceptance, session issuance, and delivery intent atomic within each operation. Enforce real route transitions and idempotency; link scanners do not consume credentials through GET | Concurrent redemption has one successful consume; injected failures leave a completed operation or unconsumed/recoverable capability; no half-enrolled user or consumed invite without a session |

**M6 Production security and bounded product flows**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M6.1 | Upgrade to a supported patched Next.js/React/runtime combination and compatible tooling; regenerate the lockfile deliberately. Audit production and build/dev dependencies; align backend constraints/lock; introduce a useful lint/type nonregression baseline | Clean locked install/build/tests pass; applicable unaccepted advisories fail CI; exceptions have owner, applicability, mitigation, and expiry; no blanket `audit || true` |
| M6.2 | Fix Docker stage ARG consumption and standalone asset placement; normalize unset/empty frontend API base to `/api`; validate Render secret paths/Blueprint and JWT PEM correspondence; test the real same-origin rewrite | Running images serve JS/CSS and auth APIs; `render blueprints validate render.yaml` succeeds; disposable deployment signs/verifies tokens and browser login/refresh/logout work through `/api` |
| M6.3 | Implement supported CSP/nonces with dynamic-render/cache qualification, exact origin/CSRF policy, trusted Host/proxy chain, credential-link no-referrer/history cleanup, and redaction across all sinks | Production hydration/navigation/crypto works while unapproved scripts are blocked; origin/port/scheme/null cases pass the chosen policy; synthetic tokens are absent from logs, referrers, telemetry, and history |
| M6.4 | Use bounded due work for both active and grace vaults; select metadata columns without loading ciphertext; add stable cursor pagination, request/body limits, documented quotas, and appropriate synchronous DB/password execution | Query counts/memory stay within the measured budget; list requests do not fetch encrypted body columns; valid existing oversized records remain readable; load results define capacity |
| M6.5 | Fix category round-trips, explicit null-clearing, action-specific errors, password cleanup, released/pending views, accurate warnings, and separate readiness indicators. Reconcile README/API/deployment/security docs | Manual owner and beneficiary journeys have accurate states and instructions; commands work in a clean environment; no misleading share-delivery or recovery-ready claim |

**M7 Release evidence and operation**

| Task | Implementation | Acceptance evidence |
|---|---|---|
| M7.1 | Restore full Playwright journeys using isolated migrated PostgreSQL fixtures and semantic UI selectors; run crypto, tenant/role isolation, races, crash recovery, migration and production configuration suites | Section 8 evidence matrix passes from an empty database and a representative migrated snapshot; tests remain independent and repeatable |
| M7.2 | Instrument checker completion/lag, due/reclaimed/dead delivery work, provider outcomes, auth abuse, and release-to-notification lag. Separate API readiness from recovery degradation; wire actionable alerts | Stopped checker/worker, invalid provider credentials, quota failure and dead letters produce expected alerts without disabling owner check-ins |
| M7.3 | Perform encrypted backup/restore rehearsal including record/key/config inventory, challenge/session invalidation, release hold and overdue-state reconciliation | Restored deployment decrypts known fixtures and completes fresh-browser recovery within measured RPO/RTO; old credentials do not revive; no premature catch-up release |
| M7.4 | Apply section 9 cutover, sole-sender verification, pilot journeys and post-release observation; retain reversible schema until evidence supports contraction | Signed release evidence links to the actual artifact/commit/schema; pilot delivers real notices and recovery; rollback/hold exercise is demonstrated |

**5 Data and transaction contracts**

Use Alembic migrations and database constraints as the authority. The structures below are logical contracts; settle exact names against the existing models at M2. Do not duplicate a working abstraction solely to match these names.

| Structure | Essential fields and constraints | Ownership |
|---|---|---|
| Existing `VaultStatus` | State, authoritative `version`, armed flag, activation timestamp, current episode; any hold must be visible to the release predicate | Release/check-in/config domain operations |
| Existing `HeartbeatConfig` | Last check-in, interval, grace, computed or consistently derived deadline | Update under the same vault-state mutex |
| Existing `Vault` material | Complete wrapped key bundle, material revision, active ceremony reference; no unwrapped key | Material/ceremony service |
| `RecoveryCeremony` | Vault, immutable unique generation, policy k/n, revision, DRAFT/FINALIZED/CANCELLED/SUPERSEDED status, timestamps, public acknowledgment metadata, initial wrapped bundle when relevant | Ceremony service; never raw shares or polynomial coefficients |
| Assignment binding | Beneficiary, ceremony, share index, assignment/contact revision; unique current index within a ceremony | Owner assignment operation |
| Drill evidence | Ceremony/material/assignment revisions, timestamp, verifier category and test artifact reference | Client or controlled test evidence; an owner report is not independently verified possession |
| `AuthChallenge` | Hash of credential, principal/assignment, purpose, contact revision, expiry, consumed/revoked timestamp, auth epoch | Enrollment/login service |
| Session family and refresh history | Principal role/id, family ID, session ID, auth epoch, revoked/expiry timestamps; indexed token hash, consumption and replacement linkage | Authentication service |
| `BusinessEvent` | Immutable event ID, vault/aggregate, kind, episode/revision, actor/time; unique aggregate revision plus kind | Domain transaction that changes the state |
| `DeliveryJob` | Event ID, recipient/contact revision, channel/kind, protected payload reference, state, attempts, due time, lease expiry/token, provider ID, result timestamps, sanitized error | Domain creates; worker updates |
| Existing `AuditEvent` | Actor, affected vault/object, event kind, sanitized metadata, correlation ID/time; durable retention policy | Staged on the domain transaction |

The new ceremony statuses require changes to the existing READY-only constraint and compatibility mapping. Invitation status, contact acceptance, session revocation, recovery ceremony status, and delivery state are separate lifecycles. A reinvitation does not reshare the vault. A repeated trigger may produce a request audit, but it cannot create another release business event.

**Atomic release and eligibility**

Use the existing `VaultStatus` row as the per-vault synchronization point for eligibility. All participating operations acquire it in the same order before rereading related mutable rows. Ensure ORM identity-map caching does not substitute an earlier read for the locked current state. Avoid helper-level commits; the domain operation stages changes and the caller owns one commit.

Automatic release requires armed=true, no administrative/restoration hold, current GRACE state, and an expired grace deadline computed from the current committed check-in/configuration. Manual release requires current owner authorization, explicit confirmation, and step-up authentication; it need not satisfy inactivity. Successful transition increments the revision and stages the release event, audit and complete eligible recipient/channel set. Losing or repeated transitions return an explicit no-change result without new release deliveries.

A check-in acquired before the automatic eligibility evaluation extends the deadline and invalidates the old episode. If release wins and commits first, a later check-in reports the terminal state and cannot reverse it. Test both orderings. Config changes and disarming invalidate observed eligibility too; define how they cancel/recompute grace rather than changing a timestamp silently. Arming a new vault starts its first check-in explicitly. Existing legitimately armed vaults retain that status through backfill.

Inject one timezone-aware clock value into each operation. Production clocks must be synchronized. During downtime, grace starts at the actual missed deadline; on recovery, evaluate current eligibility before processing overdue jobs. Do not send a stale warning after a cancelling check-in or a final warning claiming 24 hours remain when the deadline has passed.

**Delivery claims, retries and recipient safety**

Enforce a unique delivery key such as `(event_id, recipient_id, channel, kind)`, with episode uniqueness in the business event. Define required owner warnings and beneficiary notices separately. Capture a recipient/contact revision so contact replacement cancels unsent old credential jobs; already in-flight emails may arrive, but the old credentials must no longer authorize access.

Use READY, CLAIMED, RETRY_WAIT, ACCEPTED, DELIVERED, DEAD, and CANCELLED semantics, or equivalent explicit states. ACCEPTED means the provider accepted the request. DELIVERED requires the chosen provider's delivery evidence. FAILED is a recorded attempt outcome, not an invisible queue state. Store timestamps for creation, each attempt, acceptance, and delivery independently.

1. Claim only a bounded batch of due READY/RETRY_WAIT jobs or expired CLAIMED leases, using `FOR UPDATE SKIP LOCKED` and a new claim token. Commit immediately.
2. Validate that the recipient/contact/episode is still eligible; cancel obsolete work. Send outside the database transaction with a stable provider idempotency key.
3. Update the result only if the claim token still matches. A reclaimed lease prevents the stale worker from changing job state; it cannot recall an external send already accepted.
4. Retry transient/uncertain failures using exponential backoff, jitter, `Retry-After` where applicable, and a capped deadline/attempt budget. Classify invalid addresses and credential/configuration failures accurately.
5. After exhaustion, retain a DEAD job, alert, and allow an audited operator requeue without creating a second business event. A job with an expired authentication credential cannot resend that obsolete credential; issue a new purpose-bound challenge atomically instead.

Start with batches of at most 20 jobs, bounded network concurrency, a provider timeout, and leases longer than the complete send budget; measure and tune at M7. Record the selected maximum attempts and retry horizon per kind. Use current provider contracts rather than assuming an unbounded idempotency window. [Resend API reference](https://www.resend.com/docs/api-reference/emails/send-email)

Invitation and magic-link jobs need transient access to a raw credential. Keep its authentication hash in the challenge record and an encrypted, expiring payload in delivery storage, protected by a separate versioned deployment key and restricted worker access. Bind decryption context to event/recipient/purpose; delete credential payloads on expiry or completion according to retention policy. Never reuse the vault key for this encryption. Logs and provider diagnostics must not print bodies or links. Providers necessarily see authentication links; this does not give them vault shares or decryption keys.

**6 Crypto and ceremony contracts**

Keep the [current crypto format](C:/Users/prach/Documents/legacylock/frontend/lib/crypto.ts:8) compatible. Tighten writers without silently changing the protocol or deleting existing valid data.

| Version 1 object | Validation contract |
|---|---|
| Message key | Strict base64 decode; wrapped 32-byte AES-KW key is exactly 40 decoded bytes |
| Message IV | Exactly 12 decoded bytes; fresh IV per new encryption under a message key |
| Ciphertext | AES-GCM ciphertext including its 16-byte tag; enforce body policy plus tag overhead; no separate tag field in this format |
| Message KDF | None; the message key is wrapped by the vault key |
| Wrapped vault key | Exactly 40 decoded bytes, supported algorithm/version, complete salt/parameters bundle |
| Vault KDF | PBKDF2-SHA256; new version 1 material uses a 16-byte salt and the reviewed creation policy of 600,000 iterations. Readers support approved inventory values under a hard resource bound; outliers need explicit migration/repair |
| Recovery generation | Canonical 32-character lowercase hexadecimal value representing 128 bits; unique historical generation per vault |
| Recovery policy | Integer `1 <= k <= n <= 10`, consistent across policy, shares and assignment range |

Validate decoded sizes and types with real validators, not comments on `bytes` fields. For crypto replacements, accept the complete envelope and expected revision or reject it; metadata-only label/category updates are a separate documented operation. Distinguish missing object (404), invalid data (422), stale revision/unsupported operation (409), session failure (401), and release access denied (403). The browser independently validates versions and parameter bounds before expensive crypto work.

Initial setup creates an inactive draft with its immutable generation and prepared complete wrapped bundle. Share generation stays in the browser. No secret message can be written until that draft finalizes. The server records owner distribution acknowledgments as assertions; it does not claim to have verified raw shares. Finalization atomically selects the active ceremony/material and increments revisions. Cancellation leaves an initialized vault unchanged; cancelling an initial draft leaves the vault uninitialized.

If the browser loses a draft's shares, cancel/restart with fresh randomness, a new generation, and cleared acknowledgments. Previously copied shares from that abandoned draft must not be mixed into the replacement. Explain this prominently. Resharing preserves the existing master key, uses a replacement ceremony, and never advertises revocation of old quorums. Legacy shares are accepted only for explicitly classified legacy ceremonies until an owner performs a successful modern replacement; new generation-enforced ceremonies reject unversioned formats. Treat the generation check as a client correctness control, not as authority against a modified client.

Passphrase rewrap changes the complete wrapping bundle, including its new salt, while preserving the master key. Check the expected material revision, preserve message/share compatibility, and clear passphrase state after success or failure. No generic endpoint may overwrite active key material outside these domain operations.

The crypto manager privately owns the unwrapped key and binding metadata; contexts expose operations and status, not raw keys. Bind asynchronous work to an epoch and revision, recheck them before rendering/submitting, and verify expected server revision before a save. Proposed lock defaults are immediate on logout/identity change, five minutes after hiding, and fifteen minutes of visible inactivity; verify UX and policy at M2. Clear reachable plaintext/editor/share state on lock. JavaScript cleanup is best effort and does not guarantee physical memory erasure or remove user-copied clipboard/export content.

**7 Authentication and browser security contracts**

For D01, mailbox control authenticates an already accepted active beneficiary assignment. Original invitation validity and retained cookies are irrelevant to later sign-in. Short access sessions remain: owner 15 minutes and beneficiary 30 minutes are the existing baseline; retaining current 30-day/7-day refresh limits is acceptable because durable reauthentication is independent.

Magic-link requests return the same public response for unknown, revoked, pending, and eligible recipients. Scope challenges to a beneficiary assignment/contact revision and purpose, with a proposed 15-minute lifetime and one successful redemption. Rate-limit by trusted client address plus normalized recipient and enforce a resend cooldown. If one email corresponds to multiple vaults, use a noncredential recovery context to select the assignment without publicly enumerating memberships. Previously unaccepted/expired invitations require a separately specified enrollment path; do not quietly treat them as accepted.

Prefer new credential links using a browser fragment so the raw token is not in the initial server URL. Explicit user action performs a same-origin POST redemption; GET/link scanners do not consume it. Disable provider link tracking on these messages, apply no-referrer, remove the credential from history, and prohibit third-party scripts/resources on the landing page. Keep compatibility redaction for historical path/query links until their expiry.

Redeeming a challenge, marking acceptance/verification when its purpose permits, creating the session family, staging the audit, and consuming the challenge occur in one transaction. Owners designate contacts; beneficiaries establish their own sign-in. Contact replacement invalidates old challenges/families and needs reenrollment; it cannot revoke plaintext or keys already learned. Login-password recovery must never imply vault-passphrase recovery.

Refresh consumes a credential atomically and retains replacement history. Unknown, expired, revoked, and previously consumed credentials are distinct cases internally. An already consumed credential is never issued a second new session merely to accommodate concurrency. Specify a bounded no-token conflict response for expected concurrent rotations; clients wait for the coordinated winner and retry the original request once. Sustained or later recognized reuse invokes the reviewed family-revocation policy. Do not infer theft from any zero-row update. Set the conflict/replay policy at security review and test both malicious reuse and ordinary concurrency.

Use a per-principal/session-epoch refresh promise and real cross-tab exclusion where supported, such as Web Locks, plus completion signaling. BroadcastChannel messages carry metadata only, never credentials or keys. Bound lock waits, handle tab death, and define an unsupported-browser fallback that reauthenticates safely rather than concurrently consuming refresh tokens. An old account's refresh/result cannot modify a new login. [Web Locks API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API)

Owner and beneficiary access tokens should be bound to independently revocable server sessions; verify their family/auth epoch and principal role on protected requests. Logout revokes the selected session/family and clears matching cookies. Distinguish current-device logout from explicit all-device logout. During migration, retain only a bounded documented legacy-token window or require fresh sign-in after the new beneficiary flow is available.

For browser mutations, enforce exact scheme/host/port origins, trusted hosts, and a deliberate CSRF token/header policy. Reject literal null origins for cookie-authenticated unsafe operations unless a specifically reviewed protected flow requires them. For absent Origin, validate the approved Referer/CSRF fallback; SameSite is additional protection. Explicit bearer-token non-browser clients do not need a browser Origin, but still need full authentication, authorization, and any endpoint-specific request contract. Include login, refresh and redemption in the CSRF design. [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)

Use the framework's supported nonce/CSP integration so bootstrap and application scripts are covered. Verify dynamic rendering, hydration, styles, navigation, API connections, and CDN caching under the actual policy. Add restrictive object/base/form/frame rules. A curl header check alone does not demonstrate enforcement. [Next.js CSP guidance](https://nextjs.org/docs/app/guides/content-security-policy)

Fix proxy trust at both the server and application limiter: parse configured networks, validate the direct peer, select the trusted forwarded chain consistently, and ignore spoofed headers from untrusted peers. Do not assume `FORWARDED_ALLOW_IPS` fixes the separate application allowlist. Introduce shared rate-limit storage before multiple API replicas; an explicitly single-instance initial release must still prove its abuse limits.

**8 Evidence matrix and milestone completion**

Maintain deterministic fixtures and failure hooks outside production endpoints. Use independent PostgreSQL sessions for races and processes for worker interruption. Isolate every owner/vault/beneficiary test; do not recreate a master key on a shared account. Test through the real production-mode application plus migrated database for qualification, with providers replaced by controlled doubles except the small real-provider suite.

| Evidence ID | Required scenario | Passing condition |
|---|---|---|
| T01 | Expired GRACE observation, committed check-in, attempted stale release | Vault remains active; no release event/jobs |
| T02 | Check-in/config/disarm and release competing in both transaction orders | One legitimate outcome with accurate response; no contradictory timestamps/state |
| T03 | Manual and automatic trigger repeated/concurrent | One transition and business event; complete recipient/channel jobs |
| T04 | Crash before commit and after commit before any send | Full rollback or durable work that resumes |
| T05 | Worker killed after claim, before send, after provider acceptance, before result mark | Lease recovery; no stale result overwrite; duplicates limited by the documented provider contract |
| T06 | Fail/fail/succeed, permanent failure, quota timeout, one-channel failure | Real retry attempts and correct terminal/accepted states; alert and operator requeue work |
| T07 | Two grace episodes and partial recipient creation/recovery | Each episode has its intended set; cancelled/obsolete warnings are not sent |
| T08 | Repeat initial setup and injected failures/reload through draft/finalization | Existing messages survive; interrupted initial setup does not falsely finalize |
| T09 | Passphrase rewrap, concurrent material changes, wrong passphrase | Complete salt/bundle update; old messages decrypt; stale update is rejected |
| T10 | Modern/legacy shares, non-prefix quorum, duplicates, corruption, wrong generation/policy | Valid combinations reconstruct; malformed/mixed sets reject; legacy migration remains recoverable |
| T11 | Lock/account switch during decrypt/unlock/save; hidden/idle lock | No stale plaintext or save; correct principal/material binding |
| T12 | Fresh browser after simulated years, original invite consumed and refresh expired | Accepted beneficiary signs in and recovers released fixtures without owner action |
| T13 | Concurrent enrollment/verification/challenge redemption and injected commit failure | One consume; no stranded identity or consumed capability without completion |
| T14 | Parallel refresh in one/multiple tabs, tab death, reordered responses, replay | Healthy sessions recover; replay is denied; role/identity isolation holds |
| T15 | Contact change/deletion/logout with old access/refresh/challenge and queued credential jobs | Subsequent authorization rejects old identity; unsent obsolete jobs cancel |
| T16 | Missing IV, truncated key/tag, invalid KDF/version/base64, partial crypto update | Reject before persistence; valid current format round-trips |
| T17 | Cross-vault/role access, pending beneficiary, released write policy | No tenant leakage; waiting view works; terminal policy is enforced server-side |
| T18 | Unset/empty/relative API base, image runtime, same-origin browser cookies | Actual login/refresh/logout/assets work; unsupported topology fails clearly |
| T19 | Production CSP/origin/proxy spoofing, synthetic tokens in every sink | Unapproved script/mutations blocked; trusted traffic succeeds; credentials absent from captured sinks |
| T20 | Migrations on representative old data, restore with expired/consumed credentials | Valid data decrypts; sessions/challenges do not revive; release hold prevents premature catch-up |
| T21 | Checker/worker stopped, provider broken, delivery exhausted | Actionable alerts fire while owner check-ins remain available |
| T22 | Metadata pagination, realistic vault/recipient counts and payload limits | Stable pages, bounded queries/memory, measured capacity and processing lag |
| T23 | Categories, explicit null clear, loading/errors, waiting→released UX, docs | Correct round-trips and truthful instructions; clean-environment commands work |
| T24 | Clean dependency installs, security audits, builds and selected lint/type gates | Identical resolved graph in local/CI/image; applicable unaccepted advisories and new selected regressions fail the build |

T01–T24 are release gates at the declared initial capacity, not aspirational test counts. Record commit, schema version, image/lock hashes, environment profile, result, and evidence artifact for each. Existing 180 backend and 14 crypto passing results are useful baseline history; they do not replace this evidence. Store external-review evidence for M4.5 alongside the test results; a property suite alone is not an independent cryptographic review.

**9 Migration, deployment, rollback and restoration**

**Migration preparation**

Back up before any data migration and prove the restore process. Inventory the current schema and Alembic head, including uncommitted hardening migrations; never assume deployed databases have them. Use sanitized fixture snapshots containing representative active/grace/released, initialized/uninitialized, modern/legacy, accepted/pending, expired-token and failed-notification rows. Verify ciphertext and wrapped-key bytes are unchanged except where an explicit client-side operation authorizes replacement.

Expand schema first: nullable references, new tables/indexes, additional lifecycle states, and compatibility readers. Backfill authoritative state with audited rules. Do not default every existing vault to unarmed or every ceremony to finalized. An existing vault without verifiable generation metadata enters an explicit legacy/needs-review classification, while valid owner decryption is preserved. Treat malformed records as repair work; do not erase or silently rewrite encrypted data.

Keep the current active ceremony/material throughout draft migration. Add uniqueness only after reconciling conflicts safely. Tightened writers cannot make readers reject every preexisting envelope without an owner-assisted recovery/export path. Compare row counts, foreign keys, assignment uniqueness, state distributions, and representative decrypt/recovery fixtures before and after the rehearsal.

Session migration introduces new families/challenges before retiring old beneficiary refresh behavior. Require owner reauthentication or a bounded legacy window; require beneficiary reauthentication only after the durable flow works. Changing contact or auth epoch invalidates the corresponding old credentials. Do not accept legacy tokens indefinitely merely to avoid a sign-in step.

**Production configuration and qualification**

Declare one migration owner through the platform predeployment command; application startup never creates/migrates production schema. A production-mode qualification environment uses migrations, throwaway valid PEM pairs, production cookie/header settings, and controlled provider adapters. It must not expose test endpoints. Tests that need seeded verification use fixture setup rather than adding a production bypass.

Normalize frontend unset/empty API configuration to `/api`; validate absolute values only in explicitly supported topologies. Redeclare build ARGs in the builder stage and place standalone assets relative to the generated server directory. Smoke-test the built image, not only `next build`. Validate the Render Blueprint using the documented command and align secret files with actual platform mounting. Parse private/public PEMs and verify their correspondence. [Render CLI](https://render.com/docs/cli)

Add an explicit worker deployment and health/metrics contract. The delivery worker needs database, protected-payload and provider credentials; it should not receive vault decryption keys or JWT signing keys it does not use. API startup and qualification validate outbox mode and session keys; worker startup validates mandatory delivery configuration. Protect test/verification/reset routes in every production instance and proxy path.

Select a currently supported patched framework/runtime combination at implementation time. The reviewed Next.js advisories list 15.5.24 and 16.3.3 as fixes for those individual advisories; they are not a complete latest-version policy and staying on 14.2.x is insufficient for their affected ranges. Verify platform/feature applicability and the entire dependency graph. [Windows advisory](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36), [AVIF advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4)

**Sole sender and release cutover**

1. Record release artifacts, schema compatibility, passing evidence, pending holds and unresolved risks. Stop incompatible old schedulers before enabling the new eligibility contract.
2. Apply expanded migrations and verified backfill. Keep release processing held while compatibility and current state are checked; keep owner check-ins available.
3. Deploy compatible API/frontend and worker code. In a shadow comparison, only one path sends. Shadow jobs are explicitly non-deliverable and cannot later be replayed blindly.
4. Reconcile historical notification rows: accepted/sent rows become historical evidence; failed/pending rows require event/recipient/credential validation. Do not bulk resend old release or expired invitation messages.
5. Disable the old in-process delivery path and verify no old API instance still runs it. Transfer sending authority once, with an audited marker/configuration.
6. Start the worker, validate real controlled email/SMS cases and fresh-browser recovery, and then release the checker hold after overdue-state reconciliation.
7. Observe a bounded pilot cohort before wider enrollment. Record grace/check-in cancellation, release notification, authentication, and recovery outcomes. Retain rollback-compatible columns until the observation window passes.

Use a proposed minimum seven-day pilot observation alongside simulated long-deadline tests. Waiting seven days does not itself exercise years-long inactivity or all worker failure paths; the deterministic evidence does that.

**Rollback rules**

Application rollback is allowed only while the prior version understands the active schema/material/session contract. Database downgrade is not a safe way to undo a key operation. Keep additive schema and pause unsafe release/delivery code rather than restoring known race-prone behavior. External releases and messages already sent cannot be recalled. Rewrapping/rotation requires its own compatible material history and migration protocol; backups do not revoke copied keys. Holds and sender-authority changes must be audited and monitored.

**Restoration procedure**

1. Restore into an isolated environment with automatic release and delivery held. Verify database integrity and the expected backup point before serving traffic.
2. Restore required deployment configuration and wrapping metadata; maintain a separate inventory of JWT keys, provider credentials and protected-payload key versions. Never put user vault passphrases or raw shares into a service backup.
3. Advance a deployment authentication epoch or equivalent control outside the restored snapshot, invalidating restored access/refresh/challenge credentials. Session database restoration must not revive previously consumed/revoked capabilities.
4. Validate owner fixture decryption, ceremony/assignment consistency and fresh-browser beneficiary sign-in/recovery. Expired encrypted credential jobs are cancelled; new sign-in requests can issue fresh challenges.
5. Reconcile check-in loss against the measured RPO and any surviving audit/event evidence. Do not immediately release a vault because the snapshot lacks a newer check-in. Decide the necessary hold/owner notification before catch-up.
6. Reconcile delivery attempts with provider evidence and idempotency retention; document possible duplicate notices where the send result is uncertain.
7. Measure recovery time, authorize removal of holds through the documented operational role, and archive the drill evidence. Run a drill before release, after relevant schema/key changes, and at least quarterly thereafter.

**10 Monitoring, capacity and product status**

| Signal | Initial target or action | Qualification |
|---|---|---|
| Checker cadence and completion | Run every 60 seconds; alert when a successful full pass is more than five minutes late | Tune to measured due volume; capture failures and completion, not only process existence |
| Release processing lag | Five-minute proposed budget after eligible deadline, excluding explicit holds | Measure during load, downtime catch-up and contention |
| Due delivery age | Alert above five minutes; escalate sustained backlog | Measure due work, not intentionally scheduled future warnings |
| Release to provider acceptance | Proposed five-minute budget when the provider is healthy | Track acceptance separately from inbox delivery |
| Delivery failures | Immediate alert for credential/config errors and dead jobs; aggregate transient failure rate over a defined window | Avoid percentage alerts without denominator/minimum volume |
| API health | Liveness reports process responsiveness; readiness reports required schema/DB dependencies | Worker/provider degradation does not automatically remove all check-in endpoints |
| Authentication abuse | Per-recipient cooldowns and trusted-IP limits; explicit multi-instance limit contract | Exercise spoofed proxy headers and concurrent replica behavior |
| Capacity | Define supported vault/message/recipient volume from T22 before setting production quotas | Measure p95/p99 latency, DB query counts/lock waits, memory, backlog and provider throughput |
| Backup | Demonstrated RPO/RTO and restore integrity | Managed/PITR or scheduled backups must meet the target; prove it, then monitor it |

Metadata list queries select only ID, label, category, controlled tags where required, and timestamps; use an index on `(vault_id, created_at, id)` with stable descending cursor pagination. Do not load full encrypted rows to build a metadata response. The checker queries both active deadlines and due grace milestones in bounded batches; one vault's failure is isolated rather than aborting the pass. Put blocking DB/password work in appropriate synchronous handlers or bounded execution; measure before changing the database stack.

Keep coverage/readiness logic deterministic and restricted to nonsensitive metadata. Display key initialization, finalized ceremony, current distinct assignments, accepted contacts, owner distribution acknowledgment and revision-bound drill evidence separately. A configured quorum requires enough eligible distinct assignments for the chosen k; it still does not prove possession. Label an owner-reported drill as reported, and invalidate/requalify drill indicators after relevant ceremony, material or assignment changes.

Clarify privacy copy: encrypted bodies stay private to holders of the keys, while the service sees labels, categories, identities, timestamps and other metadata. Explain mailbox-based authentication, share custody, passphrase recovery limitations, lock/clipboard limitations and terminal release in the actual flows. Fix nullable phone/share-index clearing through explicit field presence rather than conflating null with no update.

**11 Finding to task traceability**

Every audit finding has a core resolution or an explicitly gated extension. Completion requires the named evidence and any relevant release-policy limitation; documentation alone cannot close a functional defect.

| Finding | Core tasks | Evidence | Closure condition or extension |
|---|---|---|---|
| F01 Stale automatic release | M1.2, M3.1 | T01, T02 | All eligibility writers share the verified transaction contract |
| F02 Repeat setup replaces key | M1.1, M4.2, M4.3 | T08, T09 | Backend guard and supported operations preserve old messages |
| F03 Beneficiary access expires permanently | M5.1, M5.3 | T12, T17 | Durable sign-in for accepted recipients without owner/cookies |
| F04 Ceremony finalizes too early | M4.2, M4.5 | T08 | Atomic finalization; interrupted drafts restart safely |
| F05 Release loses delivery intent | M3.1, M3.2 | T03, T04 | State/event/audit/jobs commit together |
| F06 Retry does not send | M3.3, M3.4 | T05, T06 | Due/abandoned work actually reaches the provider |
| F07 Manual release lacks notices | M3.1, M3.2 | T03 | Manual and automatic paths create equivalent intended jobs |
| F08 Dedup suppresses episodes/recipients | M3.2, M3.3 | T07 | Episode/recipient/channel uniqueness and partial recovery |
| F09 Owner refresh fan-out | M1.4, M5.2 | T14 | One coordinated rotation; no healthy-session revocation |
| F10 Beneficiary refresh races | M5.2 | T14 | Atomic consume and explicit family/replay contract |
| F11 Key not bound to principal | M4.4, M5.2 | T11, T14 | Account/material epoch checked for every operation |
| F12 Lock retains plaintext | M4.4 | T11 | Reachable editor/decrypted state and late results cleared |
| F13 Generation is not revocation | M4.5, M6.5 | T10, T23 | Generation enforcement and honest limitations; actual key rotation gated by E01 |
| F14 Invalid crypto envelopes | M4.1 | T16 | Strict format-compatible validation and atomic updates |
| F15 Dependency advisories | M6.1 | T24 | Applicable advisories patched or formally accepted with expiry |
| F16 Container ARG/assets | M6.2 | T18 | Built image runs the intended paths/configuration |
| F17 API prefix/cookie topology | M0.3, M6.2 | T18 | Same-origin contract tested for unset/empty/relative values |
| F18 Render secrets/keys | M6.2 | T18 | Validated Blueprint and real key mounting/signing |
| F19 Qualification contradicts app | M6.2, M7.1 | T18, T19 | Production-mode migrated fixture and valid/invalid checks |
| F20 E2E UI drift | M7.1 | T08, T12, T18, T23 | Isolated full browser journeys pass against current UI |
| F21 Missing atomic audit | M3.5, M5.4 | T04, T13 | Durable audit shares mutation transaction |
| F22 Misleading readiness | M4.5, M6.5 | T10, T23 | Separate indicators, configured quorum, revision-bound drill claims |
| F23 Arming/timing/reminders | M3.1, M6.5 | T02, T07, T21 | Explicit activation, deadline-based grace, correct recipients |
| F24 Unsafe frontend CSP | M6.3 | T19 | Deployed enforcement without hydration/crypto breakage |
| F25 Origin validation | M6.3 | T19 | Full origin and deliberate cookie/bearer CSRF handling |
| F26 Credentials in URL/logs | M1.5, M6.3 | T19 | All sinks/history/referrers covered; new link protocol qualified |
| F27 Contact/logout revocation | M1.3, M5.2, M5.3 | T15 | Role-aware logout and old-principal denial |
| F28 Scaling/inefficient queries | M6.4 | T22 | Bounded initial capacity; expansion gated by E04 |
| F29 Dependencies/static debt | M0.2, M6.1 | T24 | Reproducible installs and enforced useful baseline; deeper cleanup E05 |
| F30 Partial enrollment commits | M5.4 | T13 | Atomic redemption/enrollment/session creation |
| F31 Weak operational evidence | M1.5, M6.3, M7.2, M7.3 | T20, T21 | Real providers, trusted proxy/rate policy, alerts and restore |
| F32 UI/documentation drift | M6.5 | T23 | Correct core fields/errors/waiting/copy/docs; richer editing E05 |

**12 Gated extensions after the safe core**

| Task | Scope | Gate before enabling |
|---|---|---|
| E01 Full master-key rotation | Client prepares new wrapped message keys against a complete revisioned snapshot; backend validates manifest/completeness and atomically switches new wrapping material/ceremony | Interrupt/reload/concurrent-write/stale-manifest tests; old current-server envelopes no longer work with old key; no claim to revoke copied historical bundles; resource bounds and independent crypto review |
| E02 Authenticated metadata format | Decide whether stable vault/message identity and selected metadata enter AES-GCM additional authenticated data; version the protocol | Canonical encoding, client-generated/reserved stable ID, mutable-label rename behavior, fresh-IV re-encryption where needed, interoperable versioned migration and preservation of old readable data |
| E03 Additional beneficiary methods | Add passwords/passkeys or their recovery fallback if the chosen identity policy requires them | Credential-specific schema, recipient-controlled enrollment, account recovery/reauth/revocation threat review, compatibility and fresh-browser/device-loss journeys |
| E04 Capacity expansion | Shared rate limits, multiple API/worker replicas, due-work partitioning, increased quotas and connection budgets | Multi-replica concurrency/load/abuse tests, provider capacity, metrics, documented supported volume and unchanged release/event invariants |
| E05 Product and maintainability | Complete richer message editing/export and targeted cleanup of duplicate lookup helpers, unused scaffolding and legacy typing | Existing ciphertext/key behavior preserved; product edits have revision/conflict/error tests; cleanup remains scoped rather than a framework rewrite |

E01 and E02 are not shortcuts for closing key-lifecycle defects. If either is required in the first release, promote it into M4 and reestimate the schedule before implementation. E03 is optional only if D01 is accepted; a different selected authentication model changes M5. No unfinished extension should be exposed through a partially working API/UI.

**13 Effort, risks and execution controls**

Calendar dates cannot be committed until named capacity, data inventory and D01–D10 are known. The following are planning bands for a small repository, not measurements or promises. Estimates include implementation and focused tests; qualification/review is counted separately. Reestimate after M0/M2 and after any scope promotion.

| Workstream | Indicative effort in engineer-days | Main uncertainty |
|---|---|---|
| Baseline and containment M0–M1 | 5–9 | Runtime recovery, current data, integration of existing changes |
| Contracts and compatible schema M2 | 3–5 | Legacy data and chosen authentication/release policy |
| Atomic release/outbox M3 | 8–13 | Retry/claim correctness, provider behavior and historic notification reconciliation |
| Crypto/ceremonies M4 | 8–13 | Existing formats, distribution UX, independent review findings |
| Durable auth/sessions M5 | 8–13 | Sign-in choice, session migration and browser coordination |
| Deployment/security/product M6 | 7–12 | Framework major upgrade, CSP rendering, actual proxy topology |
| Qualification/restore/pilot M7 | 6–10 | Infrastructure access, provider tests, restoration and discovered regressions |
| Core total | 45–75 | Excludes extensions, external-review waiting and operational access delays |

For two effective implementers with some platform/review support, reserve approximately 8–12 calendar weeks for the core, including integration buffer and a seven-day pilot. A solo implementation needs a materially longer plan; derive it from available engineer-days plus review/pilot time rather than retaining the same dates. More people do not eliminate the shared-contract, migration and final-evidence dependencies. This is an initial budgeting scenario, not a confirmed team or delivery date.

| Risk | Control | Stop or escalation condition |
|---|---|---|
| Existing keys/data are inconsistent | Inventory, preserved reads, no overwrite, representative migration/decrypt tests | Any unexplained change in decryptability or byte preservation blocks cutover |
| Mailbox-based identity is unacceptable | Resolve D01 before M5 and document custody/account-recovery assumptions | Select a different model and reestimate; do not hide the tradeoff in implementation |
| Framework upgrade expands scope | Early upgrade spike, compatibility matrix and locked graph | Unsupported plugin/runtime or failing core journeys blocks target selection |
| Two delivery paths send | Single authority marker, disabled shadow delivery, old-instance reconciliation | Stop sends and reconcile before enabling new authority |
| Security flag restores known unsafe logic | Compatible rollback or visible release hold | Never roll back to stale eligibility checks to meet availability targets |
| Restore revives sessions or loses check-ins | External auth epoch, release hold and reconciliation | Serving restored auth/release without these checks is prohibited |
| Operational targets exceed capacity | Measure T22, reduce declared capacity or add gated infrastructure | No unmeasured capacity or delivery SLA claim |
| Independent review finds crypto defect | Review format/implementation before valuable-data release | Repair, retest and migrate safely before shipping |

Each implementation change needs one named owner, a second reviewer for security/transaction/crypto work, linked task/findings, affected schema/API/UX, relevant negative tests, rollback compatibility and evidence. Do not broadly run automatic audit/lint fixes across unrelated code. Use small reviewed commits; preserve existing uncommitted work until its owner integrates it.

Use the database audit as committed-event authority. Logging before a transaction commits must be marked as an attempt rather than a successfully committed mutation. Define audit retention/access and redact through structured allowlists; share indices are public metadata, while raw shares and credentials are prohibited. Outbox/payload retention must balance operational evidence with deletion of expiring secrets.

**14 Release checklist and first implementation batch**

A qualified release requires all applicable T01–T24 evidence, successful existing-data migration and restoration, reviewed crypto boundaries, real-provider qualification, patched reproducible builds, correct production topology, working owner check-ins during recovery-system degradation, and truthful product documentation. No P1 finding remains open behind a cosmetic UI guard. P2/P3 deferrals require an explicit task, owner, limitation and date; they cannot conceal an essential recovery/auth/delivery failure.

The first implementation batch should be M0.1–M0.3, M1.1–M1.4 and the production/logging containment in M1.5. In parallel, finalize M2.1 decisions and prototype the expired-grace PostgreSQL interleaving, preserving its failing baseline before the fix. Then deliver the expanded schema and complete atomic release/outbox operation before treating manual release as production-ready.

Keep a task evidence ledger with status `not started`, `in progress`, `implemented awaiting evidence`, `verified`, or `deferred with limitation`. Link the actual commit, migration, test artifact and release image. All tasks in this plan start as not implemented. The completion criterion is a dependable recovery journey under the stated failure conditions, not the number of tasks or passing unit tests.
