"""Static production configuration check for the API or independent worker.

Run inside the final service image with its real environment and mounted secrets.
This deliberately makes no database or provider network request.
"""

import argparse
import base64
import binascii
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.engine import make_url

from config import Settings, get_settings


class PreflightError(RuntimeError):
    pass


def check_database(settings: Settings) -> None:
    try:
        url = make_url(settings.database_url)
    except Exception as exc:
        raise PreflightError("DATABASE_URL is invalid") from exc
    if url.drivername not in {"postgresql+psycopg", "postgresql", "postgres"}:
        raise PreflightError("DATABASE_URL must use PostgreSQL with psycopg")
    hostname = (url.host or "").lower()
    if (
        settings.task_mode == "single_process_demo"
        and hostname.endswith(".neon.tech")
        and any(label.endswith("-pooler") for label in hostname.split("."))
    ):
        raise PreflightError(
            "TASK_MODE=single_process_demo requires a direct Neon DATABASE_URL without -pooler"
        )
    if url.query.get("sslmode") != "verify-full":
        raise PreflightError("DATABASE_URL must specify sslmode=verify-full")
    certificate = url.query.get("sslrootcert") or os.environ.get("PGSSLROOTCERT")
    if not isinstance(certificate, str) or not certificate:
        raise PreflightError("DATABASE_URL needs sslrootcert or PGSSLROOTCERT")
    if not Path(certificate).is_file():
        raise PreflightError("PostgreSQL root certificate is not readable at the configured path")


def check_delivery_keys(settings: Settings) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", settings.delivery_payload_key_id):
        raise PreflightError("DELIVERY_PAYLOAD_KEY_ID is invalid")
    try:
        current = base64.b64decode(settings.delivery_payload_key, validate=True)
        previous = json.loads(settings.delivery_payload_keys)
        if not isinstance(previous, dict):
            raise PreflightError("DELIVERY_PAYLOAD_KEYS must be a JSON object")
        keys = [current, *(base64.b64decode(value, validate=True) for value in previous.values())]
    except (ValueError, TypeError, binascii.Error) as exc:
        raise PreflightError(
            "DELIVERY_PAYLOAD_KEY and DELIVERY_PAYLOAD_KEYS must contain 32-byte base64 keys"
        ) from exc
    if settings.delivery_payload_key_id in previous or not all(
        isinstance(key_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", key_id)
        for key_id in previous
    ):
        raise PreflightError("DELIVERY_PAYLOAD_KEYS has an invalid or duplicate key ID")
    if not all(len(key) == 32 for key in keys):
        raise PreflightError("DELIVERY_PAYLOAD_KEY and DELIVERY_PAYLOAD_KEYS need 32-byte keys")


def check_jwt_pair(settings: Settings) -> None:
    try:
        private = serialization.load_pem_private_key(
            settings.jwt_private_key().encode(), password=None
        )
        public = serialization.load_pem_public_key(settings.jwt_public_key().encode())
    except Exception as exc:
        raise PreflightError("JWT private/public keys are missing, weak, or mismatched") from exc
    if (
        not isinstance(private, rsa.RSAPrivateKey)
        or not isinstance(public, rsa.RSAPublicKey)
        or private.key_size < 2048
        or private.public_key().public_numbers() != public.public_numbers()
    ):
        raise PreflightError("JWT private/public keys are missing, weak, or mismatched")


def check(role: str, settings: Settings) -> None:
    if settings.environment != "production":
        raise PreflightError("ENVIRONMENT must be production")
    if role == "api":
        settings.validate_production_api()
    elif role == "worker":
        settings.validate_production()
        if settings.task_mode == "single_process_demo":
            raise PreflightError("Separate worker is disabled in single-process demo mode")
    else:
        raise PreflightError("Role must be api or worker")
    check_database(settings)
    check_delivery_keys(settings)
    if role == "api":
        check_jwt_pair(settings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("api", "worker"))
    role = parser.parse_args().role
    try:
        check(role, get_settings())
    except Exception as exc:
        # Exception details may contain credentials or file contents. Report only
        # our static, field-named messages; never echo an arbitrary exception.
        message = (
            str(exc)
            if isinstance(exc, (PreflightError, RuntimeError))
            else "Invalid production configuration"
        )
        sys.stderr.write(f"Preflight failed: {message}\n")
        return 1
    sys.stdout.write(
        f"{role.upper()} production configuration passed static checks; "
        "connectivity is unverified.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
