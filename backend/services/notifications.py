"""Notification service — email and SMS dispatch.

Uses SendGrid for email and Twilio for SMS.
Falls back to logging when credentials are not configured.
"""

import logging
import os

logger = logging.getLogger("legacylock.notifications")

# ---------------------------------------------------------------------------
# Email — SendGrid
# ---------------------------------------------------------------------------
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
EMAIL_FROM = os.environ.get("NOTIFICATION_EMAIL_FROM", "noreply@legacylock.app")


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email. Returns True on success."""
    if not SENDGRID_API_KEY:
        logger.info("[MOCK EMAIL] to=%s subject=%s body=%s", to, subject, body[:100])
        return True

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {SENDGRID_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": EMAIL_FROM},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
            )
        if res.status_code in (200, 202):
            logger.info("Email sent to %s: %s", to, subject)
            return True
        else:
            logger.error("SendGrid error %s: %s", res.status_code, res.text[:200])
            return False
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


# ---------------------------------------------------------------------------
# SMS — Twilio
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


async def send_sms(to: str, message: str) -> bool:
    """Send an SMS. Returns True on success."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.info("[MOCK SMS] to=%s message=%s", to, message[:100])
        return True

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                data={"From": TWILIO_FROM_NUMBER, "To": to, "Body": message},
            )
        if res.status_code == 201:
            logger.info("SMS sent to %s", to)
            return True
        else:
            logger.error("Twilio error %s: %s", res.status_code, res.text[:200])
            return False
    except Exception:
        logger.exception("Failed to send SMS to %s", to)
        return False
