# LegacyLock — monitoring endpoints

`DEPLOY.md` is the source of truth for the deployment topology and release
gates. This page documents endpoint behavior and example monitor checks; it
does not mean any monitor or alert destination has been configured. Replace
example hosts with the deployed URLs and use the cadence appropriate to the
selected topology.

The current selected deployment uses one Render Free API service with
`TASK_MODE=single_process_demo`; monitor row 6 for that deployment. The separate
worker mode below is for the optional paid topology only.

Health is cheap, readiness is honest:

- `/health` → process alive (`{"status":"ok"}`, no DB touch).
- `/readyz` → can serve (`{"status":"ready"}`, runs `SELECT 1`).

Alert on `readyz` failing while `health` passes as **database/dependency
failure**, distinct from application death (both failing).

| # | Name | Type | URL | Alert when |
|---|------|------|-----|------------|
| 1 | API liveness | HTTPS monitor, typically 5 min | `https://api.example.com/health` | HTTP status ≠ 200 or `status` is not `ok` |
| 2 | API readiness | HTTPS monitor, typically 5 min | `https://api.example.com/readyz` | HTTP status ≠ 200 or `status` is not `ready` |
| 3 | Web app | HTTPS monitor, typically 5 min | `https://app.example.com/` | HTTP status ≠ 200 |
| 4 | Same-origin API route | HTTPS monitor, typically 5 min | `https://app.example.com/api/health` | HTTP status ≠ 200 or `status` is not `ok` |
| 5 | Recovery operations | Private authenticated HTTPS monitor | `https://api.example.com/operations/recovery` | HTTP 503 (`status: degraded`); HTTP 401 means monitor authentication/configuration failed |
| 6 | Single-process demo scheduler | HTTPS monitor when `TASK_MODE=single_process_demo` | `https://api.example.com/scheduler-health` | HTTP status ≠ 200; endpoint is absent (404) in other task modes |

Notes:

- Monitors 1+2 together distinguish app death from database failure.
- Monitor 4 is the same-origin contract proof: if the Vercel `/api`
  rewrite breaks, cookie auth breaks with it.
- The public liveness and readiness endpoints are unauthenticated. The
  recovery endpoint requires `Authorization: Bearer <OPERATIONS_TOKEN>` in a
  private header; never put the token in a URL. The response is 503 for any
  configured recovery degradation, including an active release hold, stale or
  failed checkpoints, overdue work, expired leases, or dead deliveries.
- In `single_process_demo` mode, `/scheduler-health` checks the in-process
  scheduler without querying the database. `/operations/recovery` provides
  the database-backed checkpoint and delivery view. In the separate-worker
  mode, monitor the worker process independently and use the recovery endpoint
  for its database checkpoint.
- Route recovery alerts separately from API/database availability. A worker
  failure must not prevent owner check-ins. Exercise stopped-worker,
  bad-provider and dead-letter alerts and record actual receipt before release;
  see [DEPLOY.md](../DEPLOY.md).
