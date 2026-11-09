# Single-process demo baseline (local, 2026-11-10)

The measurements below use Windows, Python 3.12, a disposable migrated SQLite
database, no queued deliveries, and no Render CPU limit. They are an
implementation baseline, not a Render/Neon capacity qualification.

| Processes | Idle RSS | CPU time over 12 s |
| --- | ---: | ---: |
| FastAPI only | 85.5 MB | 0.000 s |
| Worker only | 74.6 MB | 0.015 s |
| FastAPI + worker | 160.1 MB | 0.125 s |
| FastAPI with `TASK_MODE=single_process_demo` | 88.7 MB | 0.000 s |

The table is a second 12-second Windows run after the scheduler change. The
pre-change run measured 85.6 MB for API, 74.6 MB for worker, and 159.9 MB for
both. CPU time is too small and noisy over this idle window to estimate hosted
CPU use. The demo process includes its startup checker and outbox sweep. It
settled about 3.2 MB above the API-only process, rather than carrying the
separate worker's roughly 75 MB process overhead.

Five empty `work_once()` plus delivery checkpoint cycles took 174 ms total
(21.1 ms in SQLite statements). They issued 15 SELECTs, one INSERT, and four
UPDATEs. At the worker's five-second cadence, this is a database transaction
roughly every five seconds even with no work. A 30–60 second empty poll still
prevents Neon's five-minute idle suspension.

Reproduce with `backend/.venv/Scripts/python.exe backend/bench_idle.py` and
`backend/bench_resources.ps1`. The resource script runs a disposable API and
worker against a separate SQLite database and removes it after each run.

At the time of the Windows baseline, Docker's daemon was unavailable and
local PostgreSQL did not respond on port 5432. The follow-up below covers a
local constrained container and PostgreSQL fixture. Hosted Render and Neon
qualification still remains open.

## Docker Desktop qualification (local, 2026-11-10)

After Docker became available, `scripts/qualify-demo.compose.yml` built the
current backend and ran it with a PostgreSQL 17 container. Docker inspection
confirmed the API limit was **536,870,912 bytes (512 MiB)** and **100,000,000
nanoCPUs (0.1 CPU)**. The API ran one Uvicorn worker and the demo scheduler.
Test-only keys and credentials were used; email provider calls were suppressed.

The first load exposed a real pool-exhaustion bug: two of four concurrent
logins returned HTTP 500 because each login held a database connection while
waiting for the single Argon2 slot (`QueuePool size 3, overflow 0, timeout
10 s`). Login now releases its read transaction before hashing and re-reads
the user/password hash before creating a session. Registration hashes before
opening its database transaction.

With that fix, the same load produced four HTTP 200 logins (26.5–42.5 s),
one HTTP 201 registration (16.3 s), a successful health response during load
(1.0 s), one successful invitation, and two new outbox jobs in `ACCEPTED`.
Scheduler health remained HTTP 200. Sampled API memory was 74–90 MiB in the
successful run; an earlier sample during the failing run was 138 MiB. Docker
reported roughly 9–10% CPU during samples, consistent with the configured
0.1-core cap. These are sampled observations, not a continuous peak trace.

The full backend suite then passed against local PostgreSQL: **238 tests**.
The added password-rotation/pool-release regression passed separately against
PostgreSQL. This qualifies the local container and database fixture only. It
does not prove Neon autosuspend/reconnect, Render Free startup behavior, real
Resend delivery, or hosted latency. The 26–42-second concurrent login times
show that CPU, rather than idle memory, is the practical constraint for this
small demo instance.
