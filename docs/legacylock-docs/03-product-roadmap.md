# LegacyLock — Product Roadmap

## Progression

```text
Phase 1 — Core Zero-Knowledge Vault
Phase 2 — Heartbeat & Release
Phase 3 — Beneficiary & Recovery
                 ↓
          PORTFOLIO MVP
                 ↓
Phase 4 — Production Security Foundation
Phase 5 — Production Reliability
Phase 6 — Multi-Tenant Product
Phase 7 — Rich Legacy Content
Phase 8 — Mature Recovery & Key Ceremony
Phase 9 — Security & Production Posture
```

## Phase Summary

| Phase | Objective | Major Output |
|---|---|---|
| 1 | Secure storage | Working encrypted vault |
| 2 | Dead-man's switch | Heartbeat and trigger engine |
| 3 | Complete product mechanic | Beneficiary recovery MVP |
| 4 | Harden security | Auth, sessions, rate limits, logging controls |
| 5 | Harden operations | Reliable scheduler, notifications, backup, monitoring |
| 6 | Scale product model | Multi-user/multi-vault |
| 7 | Expand content | Files and structured content |
| 8 | Improve recovery UX | Share ceremony, rotation, redundancy |
| 9 | Production security | Audit, passkeys, Argon2id, pentest |

## Scope Gates

- Do not build Heartbeat before the crypto/storage path works.
- Do not build beneficiary recovery before trigger works.
- Do not build multi-tenancy before authorization is hardened.
- Do not build file storage before text storage is stable.
- Do not introduce distributed infrastructure before reliability requirements justify it.

## Portfolio Milestone

Phases 1–3 constitute the portfolio-grade MVP.

Everything after Phase 3 is production/product expansion.
