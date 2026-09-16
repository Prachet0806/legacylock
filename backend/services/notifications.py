"""Notification service — email and SMS dispatch.

Uses Resend for email and Twilio for SMS.
Falls back to logging when credentials are not configured.
"""

import html as _html
import logging

logger = logging.getLogger("legacylock.notifications")

# ---------------------------------------------------------------------------
# Email — Resend (config read lazily via _email_config for testability)
# ---------------------------------------------------------------------------


def _email_config() -> tuple[str, str]:
    try:
        from config import get_settings

        settings = get_settings()
        return (settings.resend_api_key or "", settings.notification_email_from)
    except Exception:
        import os as _os

        return (
            _os.environ.get("RESEND_API_KEY", ""),
            _os.environ.get("NOTIFICATION_EMAIL_FROM", "noreply@legacylock.app"),
        )


def _redact(value: str) -> str:
    if "@" in value and len(value) > 3:
        user, _, domain = value.partition("@")
        return f"{user[:2]}***@{domain}"
    if len(value) > 4:
        return f"{value[:2]}***{value[-2:]}"
    return "***"


async def send_email(to: str, subject: str, body: str, html_body: str | None = None) -> bool:
    """Send an email via Resend. Returns True on success."""
    api_key, email_from = _email_config()
    if not api_key:
        logger.info("[MOCK EMAIL] to=%s subject=%s", _redact(to), subject)
        return True

    try:
        import httpx

        payload: dict = {
            "from": email_from,
            "to": [to],
            "subject": subject,
            "text": body,
            "html": html_body if html_body is not None else f"<pre>{_html.escape(body)}</pre>",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if res.status_code in (200, 201, 202):
            logger.info("Email sent subject=%s", subject)
            return True
        else:
            logger.error("Resend error %s", res.status_code)
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
