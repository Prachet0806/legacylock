"""Phase B1: lifecycle state machines are explicit and enforced."""

import pytest

from services.lifecycle import (
    InvalidTransitionError,
    require_invitation_transition,
    require_notification_transition,
    require_vault_transition,
)


class TestVaultTransitions:
    def test_active_grace_triggered(self):
        require_vault_transition("active", "grace")
        require_vault_transition("grace", "triggered")
        require_vault_transition("grace", "active")

    def test_triggered_terminal(self):
        with pytest.raises(InvalidTransitionError):
            require_vault_transition("triggered", "active")
        with pytest.raises(InvalidTransitionError):
            require_vault_transition("active", "triggered")
        with pytest.raises(InvalidTransitionError):
            require_vault_transition("active", "active")


class TestInvitationTransitions:
    def test_happy_path(self):
        require_invitation_transition("pending", "sent")
        require_invitation_transition("sent", "accepted")

    def test_reinvite_after_expiry(self):
        require_invitation_transition("sent", "expired")
        require_invitation_transition("expired", "sent")

    def test_accepted_terminal(self):
        with pytest.raises(InvalidTransitionError):
            require_invitation_transition("accepted", "sent")


class TestNotificationTransitions:
    def test_pending_terminal_paths(self):
        require_notification_transition("pending", "sent")
        require_notification_transition("pending", "failed")

    def test_retry_loop(self):
        require_notification_transition("failed", "retrying")
        require_notification_transition("retrying", "failed")
        require_notification_transition("retrying", "sent")

    def test_sent_terminal(self):
        with pytest.raises(InvalidTransitionError):
            require_notification_transition("sent", "failed")


class TestVaultRuntimeGuards:
    def test_checkin_cannot_revive_triggered(self, client, auth):
        body = {"password": "TestPass123!Long", "confirm": True}
        assert client.post("/vault/trigger", json=body, headers=auth).status_code == 200
        # Grace-cancel check-in must not revive a TRIGGERED vault.
        res = client.post("/heartbeat/checkin", headers=auth)
        assert res.status_code == 409
        assert client.get("/vault/status", headers=auth).json()["status"] == "triggered"

    def test_reset_status_rejected_in_production(self, client, auth):
        from unittest.mock import patch

        from config import get_settings

        with patch.object(get_settings(), "environment", "production"):
            res = client.post(
                "/vault/reset-status",
                json={"password": "TestPass123!Long", "confirm": True},
                headers=auth,
            )
            assert res.status_code == 404
