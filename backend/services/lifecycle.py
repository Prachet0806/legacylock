"""Lifecycle state machines — single source of truth for allowed transitions.

Vault:      ACTIVE -> GRACE -> TRIGGERED  (GRACE -> ACTIVE via check-in cancel)
Beneficiary invitation: PENDING -> SENT -> ACCEPTED | EXPIRED
Notification: PENDING -> SENT | FAILED (-> RETRYING -> SENT|FAILED)

DB CHECK constraints enforce the value domains; this module enforces the
transition graph so invalid jumps (e.g. TRIGGERED -> ACTIVE without an
explicit reset) fail loudly instead of silently corrupting lifecycle state.
"""

from enum import Enum


class VaultState(str, Enum):
    ACTIVE = "active"
    GRACE = "grace"
    TRIGGERED = "triggered"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"


# Explicit transition graph. Absent edges are forbidden.
VAULT_TRANSITIONS: dict[VaultState, set[VaultState]] = {
    VaultState.ACTIVE: {VaultState.GRACE},
    VaultState.GRACE: {VaultState.ACTIVE, VaultState.TRIGGERED},
    VaultState.TRIGGERED: set(),
}

INVITATION_TRANSITIONS: dict[InvitationStatus, set[InvitationStatus]] = {
    InvitationStatus.PENDING: {InvitationStatus.SENT},
    InvitationStatus.SENT: {InvitationStatus.ACCEPTED, InvitationStatus.EXPIRED},
    InvitationStatus.ACCEPTED: set(),
    InvitationStatus.EXPIRED: {InvitationStatus.SENT},
}

NOTIFICATION_TRANSITIONS: dict[NotificationStatus, set[NotificationStatus]] = {
    NotificationStatus.PENDING: {NotificationStatus.SENT, NotificationStatus.FAILED},
    NotificationStatus.FAILED: {NotificationStatus.RETRYING},
    NotificationStatus.RETRYING: {NotificationStatus.SENT, NotificationStatus.FAILED},
    NotificationStatus.SENT: set(),
}


class InvalidTransitionError(ValueError):
    """Raised when a lifecycle transition is not in the allowed graph."""


def can_transition(current: str, target: str, graph: dict) -> bool:
    try:
        return target in graph[current]  # type: ignore[index]
    except KeyError:
        return False


def require_vault_transition(current: str, target: str) -> None:
    if not can_transition(current, target, VAULT_TRANSITIONS):
        raise InvalidTransitionError(f"vault transition {current!r} -> {target!r} forbidden")


def require_invitation_transition(current: str, target: str) -> None:
    if not can_transition(current, target, INVITATION_TRANSITIONS):
        raise InvalidTransitionError(f"invitation transition {current!r} -> {target!r} forbidden")


def require_notification_transition(current: str, target: str) -> None:
    if not can_transition(current, target, NOTIFICATION_TRANSITIONS):
        raise InvalidTransitionError(f"notification transition {current!r} -> {target!r} forbidden")
