# LegacyLock — Heartbeat & Trigger

## State Machine

```text
             ┌──────────────┐
             │    ACTIVE    │
             └──────┬───────┘
                    │ deadline reached
                    ▼
             ┌──────────────┐
             │    GRACE     │
             └──────┬───────┘
                    │ grace expires
                    ▼
             ┌──────────────┐
             │  TRIGGERED   │
             └──────────────┘

GRACE + valid check-in → ACTIVE
```

## Heartbeat

The owner periodically checks in.

A check-in updates:

- last_checkin
- next deadline
- relevant timestamps
- audit event

## Configuration

Heartbeat configuration includes:

- interval
- grace period
- notification settings

Changing configuration should generate an audit event containing old/new configuration metadata, not secrets.

## Scheduler

MVP uses a single-instance periodic scheduler.

Conceptual loop:

```text
Every hour
  ↓
Find candidate vaults
  ↓
HeartbeatService.evaluate()
```

The scheduler does not own state-transition logic.

## Trigger Service

Both entry points use the same Trigger Service:

```text
Scheduler ─────┐
               ├──→ TriggerService
Manual trigger ┘
```

## Idempotency

All trigger transitions use an atomic conditional update with a version/state guard.

Conceptual:

```sql
UPDATE vault_status
SET state = 'TRIGGERED',
    version = version + 1
WHERE vault_id = ?
  AND state = 'GRACE'
  AND version = ?;
```

If zero rows are updated, another request already changed the state or the expected version is stale.

The same principle applies to manual triggers.

## Manual Trigger

Requires:

1. Owner session
2. Re-authentication
3. Explicit confirmation
4. Atomic transition
5. Audit event

## Trigger Terminality

TRIGGERED is terminal for MVP.

The development reset endpoint is separate and cannot be available in production.

## Notification Sequence

```text
State transition
 ↓
Audit event
 ↓
Notification service
 ↓
Email/SMS/mock
```

Notification failure must not roll back an already committed trigger state.

It should be retried independently.

## Reliability Direction

Finished product may add:

- distributed-safe scheduler
- redundant monitoring
- richer warning schedules
- independent secondary heartbeat channels
