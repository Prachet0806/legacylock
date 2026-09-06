"""Notification service — email and SMS dispatch.

Uses SendGrid for email and Twilio for SMS.
Falls back to logging when credentials are not configured.
"""

import logging

logger = logging.getLogger("legacylock.notifications")

# ---------------------------------------------------------------------------
# Email — SendGrid (config read lazily via _email_config for testability)
# ---------------------------------------------------------------------------


def _email_config() -> tuple[str, str]:
    import os as _os

    return (
        _os.environ.get("SENDGRID_API_KEY", ""),
        _os.environ.get("NOTIFICATION_EMAIL_FROM", "noreply@legacylock.app"),
    )


def _redact(value: str) -> str:
    if "@" in value and len(value) > 3:
        user, _, domain = value.partition("@")
        return f"{user[:2]}***@{domain}"
    if len(value) > 4:
        return f"{value[:2]}***{value[-2:]}"
    return "***"


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email. Returns True on success."""
    api_key, email_from = _email_config()
    if not api_key:
        logger.info("[MOCK EMAIL] to=%s subject=%s", _redact(to), subject)
        return True

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": email_from},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
            )
        if res.status_code in (200, 202):
            logger.info("Email sent subject=%s", subject)
            return True
        else:
            logger.error("SendGrid error %s", res.status_code)
            return False
    except Exception:
        logger.exception("Failed to send email")
        return False


# ---------------------------------------------------------------------------
# SMS — Twilio (config read lazily for testability)
# ---------------------------------------------------------------------------


async def send_sms(to: str, message: str) -> bool:
    """Send an SMS. Returns True on success."""
    import os as _os

    sid = _os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = _os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = _os.environ.get("TWILIO_FROM_NUMBER", "")
    if not sid or not token:
        logger.info("[MOCK SMS] to=%s", _redact(to))
        return True

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"From": from_number, "To": to, "Body": message},
            )
        if res.status_code == 201:
            logger.info("SMS sent")
            return True
        else:
            logger.error("Twilio error %s", res.status_code)
            return False
    except Exception:
        logger.exception("Failed to send SMS")
        return False
