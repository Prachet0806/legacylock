"""Gated self-service registration (B-spec) + verification gate on login."""

import re
import uuid

import pytest

CODE = "test-invite-code-123"
PW = "RegisterPass123!Long"


@pytest.fixture
def captured_email(monkeypatch):
    """Capture Resend-bound emails without network (RESEND_API_KEY is empty in tests)."""
    import services.notifications as notifications

    calls = []

    async def fake(to, subject, body, html_body=None):
        calls.append({"to": to, "subject": subject, "body": body, "html": html_body})
        return True

    monkeypatch.setattr(notifications, "send_email", fake)
    return calls


def _raw_from(calls):
    assert calls, "expected a verification email"
    m = re.search(r"token=([A-Za-z0-9\-_]+)", calls[-1]["body"])
    assert m, f"no token link in email body: {calls[-1]['body'][:200]}"
    return m.group(1)


def _register(client, email, password=PW, code=CODE):
    return client.post(
        "/auth/register", json={"email": email, "password": password, "invite_code": code}
    )


class TestRegister:
    def test_happy_path_creates_user_vault_token(self, client, captured_email):
        from db import SessionLocal
        from models import EmailVerificationToken, User, Vault

        email = f"new-{uuid.uuid4().hex[:8]}@example.com"
        r = _register(client, email)
        assert r.status_code == 201
        assert r.json() == {"message": "If eligible, a verification email has been sent"}

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            assert user is not None
            assert user.email_verified_at is None
            assert db.query(Vault).filter(Vault.user_id == user.id).count() == 1
            tokens = (
                db.query(EmailVerificationToken)
                .filter(EmailVerificationToken.user_id == user.id)
                .all()
            )
            assert len(tokens) == 1
            # Hash-only: raw token from the email link is never persisted.
            raw = _raw_from(captured_email)
            assert len(raw) >= 40
            assert all(t.token_hash != raw for t in tokens)
            from services.auth import hash_token

            assert tokens[0].token_hash == hash_token(raw)
        finally:
            db.close()

    def test_login_blocked_until_verified_no_cookies(self, client, captured_email):
        email = f"unv-{uuid.uuid4().hex[:8]}@example.com"
        assert _register(client, email).status_code == 201
        r = client.post("/auth/login", json={"email": email, "password": PW})
        assert r.status_code == 403
        assert r.json()["detail"] == "Email not verified"
        assert "legacylock_owner_session" not in (r.cookies or {})

        raw = _raw_from(captured_email)
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200
        r2 = client.post("/auth/login", json={"email": email, "password": PW})
        assert r2.status_code == 200

    def test_disabled_when_no_code(self, client, monkeypatch):
        import routers.auth as auth_router

        monkeypatch.setattr(auth_router, "get_settings", lambda: type("S", (), {
            "registration_invite_code": "",
            "frontend_origin": lambda self: "http://localhost:3000",
        })())
        email = f"off-{uuid.uuid4().hex[:8]}@example.com"
        r = _register(client, email)
        assert r.status_code == 403
        assert r.json()["detail"] == "Invalid invitation"
        from db import SessionLocal
        from models import User

        db = SessionLocal()
        try:
            assert db.query(User).filter(User.email == email).first() is None
        finally:
            db.close()

    def test_wrong_code_forbidden_no_user(self, client):
        from db import SessionLocal
        from models import User

        email = f"bad-{uuid.uuid4().hex[:8]}@example.com"
        r = _register(client, email, code="wrong-code-value")
        assert r.status_code == 403
        db = SessionLocal()
        try:
            assert db.query(User).filter(User.email == email).first() is None
        finally:
            db.close()

    def test_missing_code_422(self, client):
        r = client.post(
            "/auth/register",
            json={"email": f"m-{uuid.uuid4().hex[:8]}@example.com", "password": PW},
        )
        assert r.status_code == 422

    def test_short_password_422(self, client):
        r = _register(client, f"s-{uuid.uuid4().hex[:8]}@example.com", password="short")
        assert r.status_code == 422

    def test_duplicate_verified_same_201_no_dupes(self, client, captured_email):
        from db import SessionLocal
        from models import EmailVerificationToken, User, Vault

        email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
        assert _register(client, email).status_code == 201
        raw = _raw_from(captured_email)
        assert client.post("/auth/verify-email", json={"token": raw}).status_code == 200
        n_calls = len(captured_email)

        r = _register(client, email)
        assert r.status_code == 201
        assert r.json() == {"message": "If eligible, a verification email has been sent"}
        # No-op: no new email, no extra vault/token.
        assert len(captured_email) == n_calls
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            assert db.query(Vault).filter(Vault.user_id == user.id).count() == 1
            assert (
                db.query(EmailVerificationToken)
                .filter(EmailVerificationToken.consumed_at.is_(None))
                .count()
                == 0
            )
        finally:
            db.close()

    def test_duplicate_unverified_resends_single_active(self, client, captured_email):
        from db import SessionLocal
        from models import EmailVerificationToken, User

        email = f"re-{uuid.uuid4().hex[:8]}@example.com"
        assert _register(client, email).status_code == 201
        assert _register(client, email).status_code == 201
        assert len(captured_email) == 2
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            rows = (
                db.query(EmailVerificationToken)
                .filter(
                    EmailVerificationToken.user_id == user.id,
                    EmailVerificationToken.consumed_at.is_(None),
                )
                .all()
            )
            assert len(rows) == 1
        finally:
            db.close()

    def test_email_normalized_lowercase(self, client, captured_email):
        from db import SessionLocal
        from models import User

        email = f"MiXeD-{uuid.uuid4().hex[:8]}@Example.COM"
        assert _register(client, email).status_code == 201
        db = SessionLocal()
        try:
            assert db.query(User).filter(User.email == email.lower()).first() is not None
        finally:
            db.close()

    def test_response_carries_no_secrets(self, client):
        email = f"ns-{uuid.uuid4().hex[:8]}@example.com"
        r = _register(client, email)
        assert r.status_code == 201
        body = r.text.lower()
        for needle in ("token", "password", "hash", "invite"):
            assert needle not in body or needle in "verification email", needle
