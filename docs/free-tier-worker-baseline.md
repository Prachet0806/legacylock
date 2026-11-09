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

Still required before claiming free-tier suitability: PostgreSQL query plans
and connection counts, API latency under concurrent Argon2 work and delivery,
and Docker/hosted 512 MB and 0.1 CPU tests. Docker's daemon was unavailable
during this baseline, and local PostgreSQL did not respond on port 5432.
