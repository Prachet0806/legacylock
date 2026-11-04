"""Notification service — email and SMS dispatch.

Uses Resend for email and Twilio for SMS.
Falls back to logging when credentials are not configured.
"""

import html as _html
import logging
from dataclasses import dataclass

logger = logging.getLogger("legacylock.notifications")


@dataclass(frozen=True)
class DeliveryResult:
    accepted: bool
    retryable: bool = False
    code: str | None = None
    provider_id: str | None = None
    retry_after: int | None = None


async def deliver_email(to: str, subject: str, body: str, idempotency_key: str) -> DeliveryResult:
    import httpx

    from config import get_settings

    api_key, email_from = _email_config()
    if not api_key:
        if get_settings().environment == "production":
            return DeliveryResult(False, False, "email_not_configured")
        logger.info("Development email suppressed (body and credentials omitted)")
        return DeliveryResult(True, provider_id="development-suppressed")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Idempotency-Key": idempotency_key},
                json={"from": email_from, "to": [to], "subject": subject, "text": body},
            )
        if response.status_code in (200, 201, 202):
            try:
                provider_id = response.json().get("id")
            except ValueError:
                provider_id = None
            return DeliveryResult(True, provider_id=provider_id)
        retry = response.status_code in (408, 409, 429) or response.status_code >= 500
        retry_after = response.headers.get("Retry-After", "")
        return DeliveryResult(
            False,
            retry,
            f"email_http_{response.status_code}",
            retry_after=int(retry_after) if retry_after.isdigit() else None,
        )
    except (httpx.TimeoutException, httpx.NetworkError):
        return DeliveryResult(False, True, "email_outcome_uncertain")


async def deliver_sms(to: str, body: str, idempotency_key: str) -> DeliveryResult:
    from config import get_settings

    if not get_settings().sms_enabled:
        return DeliveryResult(False, False, "sms_disabled")
    # Twilio Messages has no assumed send-idempotency guarantee. Uncertain
    # requests require operator reconciliation rather than automatic duplicates.
    ok = await send_sms(to, body)
    return DeliveryResult(ok, False, None if ok else "sms_reconcile_required")


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
        from config import get_settings

        logger.info("Email suppressed: credentials unavailable (content omitted)")
        return get_settings().environment != "production"

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
        logger.warning("SMS unavailable: credentials missing")
        return False

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
