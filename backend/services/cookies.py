"""Central session-cookie helpers — single source of truth (Phase B3/B5).

All cookie flags (HttpOnly, SameSite=Lax, Secure-in-prod, Path=/) live here
so owner/beneficiary login/refresh/logout cannot drift.
"""

from fastapi import Response

from config import get_settings


def _secure() -> bool:
    try:
        return get_settings().environment == "production"
    except Exception:
        return False


def set_owner_session(response: Response, access_token: str, refresh_token: str) -> None:
    s = get_settings()
    sec = _secure()
    response.set_cookie(
        key=s.session_cookie_name_owner,
        value=access_token,
        httponly=True,
        secure=sec,
        samesite="lax",
        max_age=15 * 60,
        path="/",
    )
    response.set_cookie(
        key=s.session_cookie_name_owner_refresh,
        value=refresh_token,
        httponly=True,
        secure=sec,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
        path="/",
    )


def clear_owner_session(response: Response) -> None:
    s = get_settings()
    sec = _secure()
    response.delete_cookie(
        s.session_cookie_name_owner, path="/", secure=sec, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        s.session_cookie_name_owner_refresh, path="/", secure=sec, httponly=True, samesite="lax"
    )


def set_beneficiary_session(response: Response, access_token: str, raw_refresh: str) -> None:
    s = get_settings()
    sec = _secure()
    response.set_cookie(
        key=s.session_cookie_name_beneficiary,
        value=access_token,
        httponly=True,
        secure=sec,
        samesite="lax",
        max_age=30 * 60,
        path="/",
    )
    response.set_cookie(
        key=s.session_cookie_name_beneficiary_refresh,
        value=raw_refresh,
        httponly=True,
        secure=sec,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def clear_beneficiary_session(response: Response) -> None:
    s = get_settings()
    sec = _secure()
    response.delete_cookie(
        s.session_cookie_name_beneficiary, path="/", secure=sec, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        s.session_cookie_name_beneficiary_refresh,
        path="/",
        secure=sec,
        httponly=True,
        samesite="lax",
    )
