"""Local PostgreSQL test-only encrypted dump/restore rehearsal.

Creates a NEW loopback database; refuses existing destinations. Backup key
exists only in this process. This does not qualify managed backups or key escrow.
Set RESTORE_FIXTURE_PASSPHRASE to a known synthetic browser fixture passphrase.
"""

import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

import psycopg
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from config import get_settings
from db import normalize_database_url
from models import AuthSession, User, Vault, VaultMessage
from ops import inventory, quarantine_restored_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    client = parser.add_mutually_exclusive_group(required=True)
    client.add_argument("--pg-bin")
    client.add_argument("--pg-image", help="Matching PostgreSQL Docker client image (Linux CI)")
    parser.add_argument("--report", required=True)
    parser.add_argument("--fixture-output", required=True)
    args = parser.parse_args()
    settings = get_settings()
    source = make_url(normalize_database_url(settings.database_url))
    passphrase = os.environ.get("RESTORE_FIXTURE_PASSPHRASE", "")
    if (
        settings.environment != "test"
        or source.host not in ("localhost", "127.0.0.1")
        or not source.drivername.startswith("postgresql")
        or not passphrase
        or not re.fullmatch(r"legacylock_restore_[a-z0-9_]+", args.target)
        or args.target == source.database
    ):
        parser.error(
            "Requires a loopback PostgreSQL test source, new legacylock_restore_* target and synthetic fixture passphrase"
        )
    began = time.monotonic()
    source_engine = create_engine(source)
    with Session(source_engine) as db:
        before = inventory(db)
    target = source.set(database=args.target)
    admin = source.set(drivername="postgresql", database="postgres")
    with psycopg.connect(
        admin.render_as_string(hide_password=False), autocommit=True
    ) as connection:
        if connection.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (args.target,)
        ).fetchone():
            parser.error("Destination already exists; no database will be overwritten")
        connection.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(args.target))
        )
    # CLI credentials are supplied in env, never argv or captured output.
    child_env = dict(
        os.environ,
        PGHOST=source.host,
        PGPORT=str(source.port or 5432),
        PGUSER=source.username or "",
        PGPASSWORD=source.password or "",
    )

    def command(name):
        if args.pg_image:
            return [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "-i",
                "-e",
                "PGHOST",
                "-e",
                "PGPORT",
                "-e",
                "PGUSER",
                "-e",
                "PGPASSWORD",
                args.pg_image,
                name,
            ]
        return [str(Path(args.pg_bin) / name)]

    dump = subprocess.run(
        command("pg_dump") + ["--format=custom", "--dbname", source.database],
        env=child_env,
        capture_output=True,
        check=True,
    ).stdout
    key, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    protected = AESGCM(key).encrypt(nonce, dump, b"legacylock-isolated-restore-v1")
    del dump
    restored_bytes = AESGCM(key).decrypt(nonce, protected, b"legacylock-isolated-restore-v1")
    subprocess.run(
        command("pg_restore")
        + [
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--dbname",
            args.target,
        ],
        input=restored_bytes,
        env=child_env,
        capture_output=True,
        check=True,
    )
    del restored_bytes, key
    target_engine = create_engine(target)
    old_epoch = settings.auth_epoch
    settings.release_hold, settings.delivery_enabled, settings.auth_epoch = (
        True,
        False,
        "restore-" + secrets.token_hex(16),
    )
    recovered, selected_owner = 0, None
    with Session(target_engine) as db:
        assert inventory(db)["crypto_snapshot_sha256"] == before["crypto_snapshot_sha256"]
        quarantine_restored_database(db, old_epoch)
        after = inventory(db)
        assert after["crypto_snapshot_sha256"] == before["crypto_snapshot_sha256"]
        assert not db.query(AuthSession).filter_by(revoked=False).count()
        for vault in db.query(Vault).filter(Vault.wrapped_vmk.isnot(None)):
            try:
                parameters = json.loads(vault.vmk_kdf_parameters)
                kek = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=base64.b64decode(vault.vmk_kdf_salt),
                    iterations=parameters["iterations"],
                ).derive(passphrase.encode())
                vmk = aes_key_unwrap(kek, base64.b64decode(vault.wrapped_vmk))
            except (ValueError, TypeError, KeyError, InvalidUnwrap):
                continue
            for message in db.query(VaultMessage).filter_by(vault_id=vault.id):
                mek = aes_key_unwrap(vmk, base64.b64decode(message.wrapped_mek))
                plain = (
                    AESGCM(mek)
                    .decrypt(
                        base64.b64decode(json.loads(message.crypto_metadata)["iv"]),
                        base64.b64decode(message.ciphertext),
                        None,
                    )
                    .decode()
                )
                if plain.startswith("The golden plaintext"):
                    recovered += 1
                    selected_owner = db.get(User, vault.user_id).email
                del plain, mek
            del vmk, kek
        assert recovered >= 3, "Known browser fixture was not restored and decrypted"
    Path(args.fixture_output).write_text(
        json.dumps(
            {
                "owner_email": selected_owner,
                "database": args.target,
                "auth_epoch": settings.auth_epoch,
            }
        ),
        encoding="utf-8",
    )
    report = {
        "source": "isolated browser PostgreSQL database",
        "target": "new loopback PostgreSQL database",
        "schema": "0008_delivery_attempts",
        "encrypted_backup_bytes": len(protected),
        "crypto_snapshot_sha256": after["crypto_snapshot_sha256"],
        "vaults": after["vaults"],
        "messages": after["messages"],
        "known_messages_decrypted": recovered,
        "all_restored_sessions_revoked": True,
        "release_hold": True,
        "delivery_enabled": False,
        "elapsed_seconds": round(time.monotonic() - began, 2),
        "limits": "Synthetic local encrypted in-memory backup; does not establish production RPO/RTO, durable key escrow or fresh-beneficiary mailbox delivery",
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
