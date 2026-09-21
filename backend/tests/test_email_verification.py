"""Email verification lifecycle (Resend-backed, hash-only single-use tokens)."""

import uuid
from datetime import UTC, datetime, timedelta


def _make_unverified(client):
    """Register via API; return (email, raw_token) for the active token.

    The register endpoint emails the link but never returns the raw token,
    so re-issue once with a capturing sender to obtain it deterministically
    (single-active semantics revoke the register-time token — same as a user
    clicking the newest email).
    """
    import asyncio

    import services.notifications as notifications
    from db import SessionLocal
    from models import User
    from services.email_verification import issue_verification

    email = f"v-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "VerifyPass123!Long",
            "invite_code": "test-invite-code-123",
        },
    )
    assert r.status_code == 201

    links = []

    async def fake(to, subject, body, html_body=None):
        links.append(body)
        return True

    orig = notifications.send_email
    notifications.send_email = fake  # type: ignore[method-assign]
    try:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            raw = asyncio.run(issue_verification(db, user))
        finally:
            db.close()
    finally:
        notifications.send_email = orig  # type: ignore[method-assign]
    assert links and raw in links[-1]
    return email, raw


class TestVerifyEmail:
    def test_verify_happy_sets_verified_and_login_works(self, client):
        from db import SessionLocal
        from models import AuditEvent, User

        email, raw = _make_unverified(client)
        r = client.post("/auth/verify-email", json={"token": raw})
        assert r.status_code == 200
        assert r.json() == {"message": "Email verified"}

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            assert user.email_verified_at is not None
            kinds = {e.event_type for e in db.query(AuditEvent).all()}
            assert "auth.verified" in kinds
        finally:
            db.close()

        login = client.post(
            "/auth/login", json={"email": email, "password": "VerifyPass123!Long"}
        )
        assert login.status_code == 200
        me = client.get("/auth/me", headers=_bearer(client, email))
        assert me.json()["email_verified"] is True

    def test_reuse_rejected(self, client):
        _, raw = _make_unverified(client)
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200
        r = client.post("/auth/verify-email", json={"token": raw})
        assert r.status_code == 400
        assert r.json()["detail"] == "Invalid or expired link"

    def test_garbage_rejected(self, client):
        r = client.post("/auth/verify-email", json={"token": "not-a-real-token-value"})
        assert r.status_code == 400

    def test_expired_rejected(self, client):
        from db import SessionLocal
        from models import EmailVerificationToken
        from services.auth import hash_token

        _, raw = _make_unverified(client)
        db = SessionLocal()
        try:
            row = (
                db.query(EmailVerificationToken)
                .filter(EmailVerificationToken.token_hash == hash_token(raw))
                .first()
            )
            row.expires_at = datetime.now(UTC) - timedelta(hours=1)
            db.commit()
        finally:
            db.close()
        r = client.post("/auth/verify-email", json={"token": raw})
        assert r.status_code == 400

    def test_single_active_token(self, client):
        import asyncio

        from db import SessionLocal
        from models import EmailVerificationToken, User
        from services.email_verification import issue_verification

        email, raw1 = _make_unverified(client)
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            raw2 = asyncio.run(issue_verification(db, user))
        finally:
            db.close()
        assert raw1 != raw2
        # First link is dead after re-issue.
        assert client.post("/auth/verify-email", json={"token": raw1}).status_code == 400
        assert client.post("/auth/verify-email", json={"token": raw2}).status_code == 200
        db = SessionLocal()
        try:
            assert (
                db.query(EmailVerificationToken)
                .filter(EmailVerificationToken.consumed_at.is_(None))
                .count()
                == 0
            )
        finally:
            db.close()


class TestResendVerification:
    def test_unknown_email_always_200(self, client):
        r = client.post(
            "/auth/resend-verification", json={"email": "ghost@example.com"}
        )
        assert r.status_code == 200
        assert "verification" in r.json()["message"]

    def test_verified_account_sends_nothing(self, client):
        import services.notifications as notifications

        email, raw = _make_unverified(client)
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200

        sent = []
        orig = notifications.send_email

        async def fake(to, subject, body, html_body=None):
            sent.append(to)
            return True

        notifications.send_email = fake  # type: ignore[method-assign]
        try:
            r = client.post("/auth/resend-verification", json={"email": email})
        finally:
            notifications.send_email = orig  # type: ignore[method-assign]
        assert r.status_code == 200
        assert sent == []


class TestResendProvider:
    def test_mock_without_key(self, client):
        import asyncio

        from services.notifications import send_email

        assert asyncio.run(send_email("a@example.com", "s", "b")) is True

    def test_resend_endpoint_used_when_key_set(self, monkeypatch):
        import asyncio

        import services.notifications as notifications

        monkeypatch.setattr(
            notifications, "_email_config", lambda: ("re_test_key", "noreply@t.example")
        )
        posted = {}

        class FakeResp:
            status_code = 201

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                posted["url"] = url
                posted["auth"] = headers.get("Authorization")
                posted["json"] = json
                return FakeResp()

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: FakeClient())
        ok = asyncio.run(notifications.send_email("u@example.com", "Hi", "body"))
        assert ok is True
        assert posted["url"] == "https://api.resend.com/emails"
        assert posted["auth"] == "Bearer re_test_key"
        assert posted["json"]["to"] == ["u@example.com"]
        assert "sendgrid" not in posted["url"]


def _bearer(client, email):
    from db import SessionLocal
    from models import User, Vault
    from services.auth import create_access_token

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        vault = db.query(Vault).filter(Vault.user_id == user.id).first()
        token = create_access_token(user.id, vault.id if vault else None, role="owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


class TestIssueVerificationEndpoint:
    def _register(self, client, email):
        res = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "VerifyPass123!Long",
                "invite_code": "test-invite-code-123",
            },
        )
        assert res.status_code == 201

    def test_returns_verifiable_link(self, client):
        import uuid

        email = f"t-{uuid.uuid4().hex[:8]}@example.com"
        self._register(client, email)
        res = client.post("/auth/test-issue-verification", json={"email": email})
        assert res.status_code == 200
        link = res.json()["link"]
        assert "/verify-email?token=" in link
        raw = link.split("token=")[1]
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200

    def test_unknown_email_404(self, client):
        res = client.post("/auth/test-issue-verification", json={"email": "ghost@example.com"})
        assert res.status_code == 404

    def test_verified_account_404(self, client):
        email, raw = _make_unverified(client)
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200
        res = client.post("/auth/test-issue-verification", json={"email": email})
        assert res.status_code == 404

    def test_resend_cooldown_stays_generic(self, client):
        import uuid

        email = f"c-{uuid.uuid4().hex[:8]}@example.com"
        self._register(client, email)
        # Immediate resend hits the per-email cooldown but stays generic-200.
        res = client.post("/auth/resend-verification", json={"email": email})
        assert res.status_code == 200
        assert res.json() == {
            "message": "If the account needs verification, an email has been sent"
        }
