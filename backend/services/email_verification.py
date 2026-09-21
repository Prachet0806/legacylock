"""Owner email verification — hash-only single-use tokens sent via Resend.

The raw token travels once inside the email link and is never persisted,
logged, or returned by any other endpoint (same pattern as beneficiary
invitation hashes).
"""

import html as _html
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from config import get_settings
from models import EmailVerificationToken, User
from services.audit import record_audit
from services.auth import hash_token


def _ttl() -> timedelta:
    try:
        hours = get_settings().email_verification_ttl_hours
    except Exception:
        hours = 24
    return timedelta(hours=max(1, hours))


def verification_link(raw: str) -> str:
    try:
        origin = get_settings().frontend_origin()
    except Exception:
        origin = "http://localhost:3000"
    return f"{origin}/verify-email?token={raw}"


_RESEND_COOLDOWN = timedelta(minutes=5)


class VerificationCooldown(Exception):
    """Raised when a resend arrives inside the per-email cooldown window."""


async def issue_verification(
    db: Session, user: User, enforce_cooldown: bool = False
) -> str:
    """Create a fresh single-use token for user, email the link, return raw.

    Prior unconsumed tokens are revoked so only the newest link works.
    With enforce_cooldown=True (public resend endpoint only), a re-issue
    inside the 5-minute per-email window raises VerificationCooldown instead
    of sending mail — supplementing IP rate limits against email spam.
    Registration-time issuance never enforces the cooldown.
    Email-send failure is logged, not raised — the user can resend.
    """
    from services.notifications import send_email

    if enforce_cooldown:
        latest = (
            db.query(EmailVerificationToken)
            .filter(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.created_at.desc())
            .first()
        )
        if latest is not None and latest.consumed_at is None:
            created = latest.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if datetime.now(UTC) - created < _RESEND_COOLDOWN:
                raise VerificationCooldown("Verification email cooldown active")

    # Single-active: drop stale unconsumed tokens.
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.consumed_at.is_(None),
    ).delete(synchronize_session=False)

    raw = secrets.token_urlsafe(32)
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + _ttl(),
        )
    )
    record_audit(db, None, "owner", user.id, "auth.verification_sent", {})
    db.commit()

    link = verification_link(raw)
    text = (
        "Welcome to LegacyLock.\n\n"
        "Verify your email to activate your owner account:\n"
        f"{link}\n\n"
        f"This link expires in {_ttl().total_seconds() / 3600:.0f} hours and is single-use. "
        "If you did not register, ignore this email."
    )
    safe_link = _html.escape(link)
    html_body = (
        "<p>Welcome to LegacyLock.</p>"
        f'<p><a href="{safe_link}">Verify your email</a></p>'
        f"<p>Or paste this link:<br>{safe_link}</p>"
        "<p>This link expires soon and is single-use.</p>"
    )
    try:
        await send_email(user.email, "LegacyLock — Verify your email", text, html_body)
    except Exception:
        pass
    return raw


def consume_verification(db: Session, raw: str) -> User | None:
    """Redeem a raw token. Returns the user on success, None if invalid/expired/used.

    Atomic single-use: the conditional UPDATE only flips unconsumed rows, so
    concurrent redemptions cannot both succeed. Expiry is checked in Python
    (SQLite stores naive datetimes; comparing against aware `now()` in SQL
    would misbehave) — an expired token is still burned, which preserves the
    single-use promise.
    """
    if not raw or len(raw) > 256:
        return None
    now = datetime.now(UTC)
    flipped = (
        db.query(EmailVerificationToken)
        .filter(
            EmailVerificationToken.token_hash == hash_token(raw),
            EmailVerificationToken.consumed_at.is_(None),
        )
        .update({EmailVerificationToken.consumed_at: now}, synchronize_session=False)
    )
    db.commit()
    if not flipped:
        return None
    row = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.token_hash == hash_token(raw))
        .first()
    )
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        return None
    user.email_verified_at = now
    user.updated_at = now
    record_audit(db, None, "owner", user.id, "auth.verified", {})
    db.commit()
    db.refresh(user)
    return user
