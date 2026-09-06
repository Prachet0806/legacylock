# LegacyLock — Architecture Decisions

## ADR-001 — VMK Is the Shamir Secret

**Decision:** Shamir's Secret Sharing splits a randomly generated high-entropy Vault Master Key.

**Reason:** Splitting the user's password would couple recovery security to human password entropy.

---

## ADR-002 — MEK Per Message

**Decision:** Every message receives a random Message Encryption Key.

**Reason:** Limits key reuse and avoids expensive password-based derivation for every message.

---

## ADR-003 — Client-Side Shamir Reconstruction

**Decision:** The browser reconstructs the VMK.

**Reason:** The server must not possess the reconstructable secret.

---

## ADR-004 — No Server-Mediated Share Delivery

**Decision:** LegacyLock never emails or SMSes raw Shamir shares.

**Reason:** The platform should not become the delivery channel for the secret that protects the vault.

---

## ADR-005 — Login Password and Vault Secret Are Separate

**Decision:** Authentication credentials and cryptographic vault material are independent.

**Reason:** Account recovery must not imply vault-key recovery.

---

## ADR-006 — Lightweight User → Vault Model in MVP

**Decision:** Keep one-owner UX while modeling ownership explicitly.

**Reason:** Avoid baking a singleton database architecture into the product.

---

## ADR-007 — Owner and Beneficiary Sessions Are Distinct

**Decision:** Use separate session types and server-side capabilities.

**Reason:** Beneficiary access must never become owner authorization.

---

## ADR-008 — Heartbeat and Trigger Are Separate Components

**Decision:** Heartbeat evaluates whether a transition should happen; TriggerService performs it.

**Reason:** Clear ownership and shared idempotency for automatic/manual triggers.

---

## ADR-009 — Atomic Trigger Transitions

**Decision:** Both automatic and manual triggers use conditional versioned database updates.

**Reason:** Prevent duplicate transitions under retries, double clicks, or concurrent scheduler execution.

---

## ADR-010 — Single-Instance Scheduler for MVP

**Decision:** Use a basic single-instance scheduler.

**Reason:** Keeps MVP complexity low. Database state transitions remain concurrency-safe.

---

## ADR-011 — Light Repository Layer

**Decision:** Use repositories for database isolation without excessive abstraction.

**Reason:** Provides maintainability without enterprise-scale ceremony for a solo portfolio project.

---

## ADR-012 — Separate Operational Logging from Audit Events

**Decision:** Operational logs and security audit events are separate.

**Reason:** Prevent accidental secret leakage and provide a reliable security timeline.

---

## ADR-013 — Invitation and Share Lifecycles Are Independent

**Decision:** Reissuing an invitation does not regenerate a Shamir share.

**Reason:** Losing a link and losing a cryptographic share are fundamentally different events.

---

## ADR-014 — Same Valid Share Submission Is Idempotent

**Decision:** Re-submitting the same valid share is a no-op.

**Reason:** Avoid accidental beneficiary self-lockout while maintaining rate limits for invalid submissions.

---

## ADR-015 — No Microservices in MVP

**Decision:** Use one FastAPI application with modular routers/services.

**Reason:** The workload does not justify distributed-system complexity.

---

## ADR-016 — Text-Only MVP

**Decision:** Keep content to small text messages.

**Reason:** File encryption introduces object storage, chunking, memory, and integrity concerns that are better isolated into a later phase.

---

## ADR-017 — VMK Persistence and At-Rest Wrapping

**Decision:** Persist the VMK only in client-side-wrapped form using a KEK derived from a dedicated vault passphrase.

**Reason:** The VMK is random and cannot be regenerated from the login password, but it must survive owner logout/refresh/restart. Wrapping provides persistence without exposing the VMK to the backend.

**Canonical specification:** See `19-adr-vmk-persistence.md`.

## Coverage Intelligence Decision

LegacyLock uses one primary `MessageCategory` per message and controlled `CoverageTag[]` values for granular coverage evaluation. This keeps the MVP message model simple while supporting meaningful partial coverage scores.

The Coverage Intelligence Engine is owner-only, deterministic, and metadata-only. AI explanation is optional and never authoritative.

## Persistence Taxonomy

Persistence and repository concerns remain a distinct architectural layer (C12); this revision does not fold persistence into the feature services.
