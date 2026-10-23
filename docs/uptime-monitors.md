# LegacyLock — UptimeRobot monitors (Phase D)

Health is cheap, readiness is honest:

- `/health` → process alive (`{"status":"ok"}`, no DB touch).
- `/readyz` → can serve (`{"status":"ready"}`, runs `SELECT 1`).

Alert on `readyz` failing while `health` passes as **database/dependency
failure**, distinct from application death (both failing).

| # | Name | Type | URL | Alert when |
|---|------|------|-----|------------|
| 1 | legacylock-api-alive | HTTPS monitor, 5 min | `https://api.example.com/health` | keyword `ok` absent or status ≠ 200 |
| 2 | legacylock-api-ready | HTTPS monitor, 5 min | `https://api.example.com/readyz` | keyword `ready` absent or status ≠ 200 |
| 3 | legacylock-app | HTTPS monitor, 5 min | `https://app.example.com/` | status ≠ 200 |
| 4 | legacylock-app-api-rewrite | HTTPS monitor, 5 min | `https://app.example.com/api/health` | keyword `ok` absent — catches Vercel rewrite regressions |
| 5 | legacylock-recovery | Restricted HTTPS monitor, 1 min | `https://api.example.com/operations/recovery` | status 503: hold, stale/error checker or delivery checkpoint, late jobs, expired lease, or dead letter |

Notes:

- Monitors 1+2 together distinguish app death from DB failure.
- Monitor 4 is the same-origin contract proof: if the Vercel `/api`
  rewrite breaks, cookie auth breaks with it.
- No `/api/v1` paths exist — routing stays unversioned through Phase D.
  Versioning belongs to Phase C.
- Monitor 5 requires its dedicated bearer token in a private header. Never put it in the URL. Choose a monitoring system that can keep custom-header credentials private; this table does not prove UptimeRobot or another provider has been configured.
- Route recovery alerts separately from API/database availability. A worker failure must not prevent owner check-ins. Exercise stopped-worker, bad-provider and dead-letter alerts and record actual receipt before release; see [DEPLOY.md](../DEPLOY.md).
