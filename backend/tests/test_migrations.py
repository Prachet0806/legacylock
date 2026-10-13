"""Migration drift: migrated schema must match SQLAlchemy models exactly."""

import tempfile
from pathlib import Path

from sqlalchemy import MetaData, create_engine, text


def _migrated_metadata() -> MetaData:
    from alembic.config import Config

    from alembic import command

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    url = f"sqlite:///{tmp.name}"
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    import os

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
    meta = MetaData()
    meta.reflect(bind=create_engine(url))
    return meta


def _norm_type(t) -> str:
    name = type(t).__name__.upper()
    # SQLite reflection reports String(n) as VARCHAR; same DDL family.
    if name in ("VARCHAR", "STRING", "TEXT", "CHAR"):
        return "STRING"
    return name


def test_migrated_schema_matches_models():
    """Every model table/column/constraint must exist as migrated (and vice versa)."""
    from db import Base

    migrated = _migrated_metadata()
    model_tables = {t for t in Base.metadata.tables if t != "alembic_version"}
    migrated_tables = {t for t in migrated.tables if t != "alembic_version"}
    assert migrated_tables == model_tables, f"table drift: {migrated_tables ^ model_tables}"
    for name in sorted(model_tables):
        mt, gt = Base.metadata.tables[name], migrated.tables[name]
        mc = {c.name: (c.nullable, c.primary_key, _norm_type(c.type)) for c in mt.columns}
        gc = {c.name: (c.nullable, c.primary_key, _norm_type(c.type)) for c in gt.columns}
        assert mc == gc, f"column drift in {name}: model={mc} migrated={gc}"
        mi = {(tuple(sorted(c.name for c in ix.columns)), bool(ix.unique)) for ix in mt.indexes}
        gi = {(tuple(sorted(c.name for c in ix.columns)), bool(ix.unique)) for ix in gt.indexes}
        # SQLite reflection omits PK indexes (covered by the primary_key check above).
        pk = next((c.name for c in mt.columns if c.primary_key), None)
        mi = {ix for ix in mi if ix[0] != (pk,)}
        gi = {ix for ix in gi if ix[0] != (pk,)}
        assert mi <= gi, f"index missing in migrated {name}: {mi - gi}"


def test_expand_migration_preserves_real_legacy_crypto_and_checkin_state(tmp_path, monkeypatch):
    import base64
    import json
    from datetime import UTC, datetime

    from alembic.config import Config
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.keywrap import aes_key_unwrap, aes_key_wrap

    from alembic import command

    url = f"sqlite:///{tmp_path / 'representative-old-schema.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    command.upgrade(cfg, "0005_hardening_constraints")
    db_engine = create_engine(url)
    vmk, kek, mek, iv = (
        bytes(range(32)),
        bytes(range(32, 64)),
        bytes(reversed(range(32))),
        bytes(range(12)),
    )
    wrapped = base64.b64encode(aes_key_wrap(kek, vmk)).decode()
    message_key = base64.b64encode(aes_key_wrap(vmk, mek)).decode()
    ciphertext = base64.b64encode(
        AESGCM(mek).encrypt(iv, b"legacy fixture survives expansion", None)
    ).decode()
    stamps = {"now": datetime.now(UTC)}
    with db_engine.begin() as connection:
        for ident in (1, 2, 3):
            connection.execute(
                text(
                    "INSERT INTO \"user\" (id,email,password_hash,created_at,updated_at) VALUES (:id,:email,'synthetic-hash',:now,:now)"
                ),
                dict(stamps, id=ident, email=f"migration-{ident}@example.com"),
            )
            connection.execute(
                text(
                    "INSERT INTO vault (id,user_id,name,wrapped_vmk,vmk_crypto_version,vmk_kdf_algorithm,vmk_kdf_salt,vmk_kdf_parameters,created_at,updated_at) VALUES (:id,:id,'Legacy',:wrapped,1,'PBKDF2-SHA256',:salt,:params,:now,:now)"
                ),
                dict(
                    stamps,
                    id=ident,
                    wrapped=wrapped if ident != 2 else None,
                    salt=base64.b64encode(bytes(range(16))).decode(),
                    params=json.dumps({"iterations": 600000}),
                ),
            )
            connection.execute(
                text(
                    "INSERT INTO vault_status (vault_id,state,updated_at) VALUES (:id,:state,:now)"
                ),
                dict(stamps, id=ident, state="triggered" if ident == 3 else "active"),
            )
        connection.execute(
            text(
                "INSERT INTO heartbeat_config (vault_id,last_check_in,updated_at) VALUES (1,:now,:now)"
            ),
            stamps,
        )
        connection.execute(
            text(
                "INSERT INTO vault_message (vault_id,label,ciphertext,wrapped_mek,crypto_metadata,created_at,updated_at) VALUES (1,'Fixture',:ciphertext,:wrapped,:metadata,:now,:now)"
            ),
            dict(
                stamps,
                ciphertext=ciphertext,
                wrapped=message_key,
                metadata=json.dumps({"iv": base64.b64encode(iv).decode(), "v": 1}),
            ),
        )
    command.upgrade(cfg, "head")
    with db_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id,wrapped_vmk,recovery_status,material_revision FROM vault ORDER BY id")
        ).all()
        assert rows == [
            (1, wrapped, "LEGACY", 1),
            (2, None, "UNINITIALIZED", 0),
            (3, wrapped, "LEGACY", 1),
        ]
        assert connection.execute(
            text("SELECT state,armed FROM vault_status ORDER BY vault_id")
        ).all() == [("active", 1), ("active", 0), ("triggered", 0)]
        persisted = connection.execute(
            text("SELECT ciphertext,wrapped_mek FROM vault_message")
        ).one()
        assert persisted == (ciphertext, message_key)
        recovered_vmk = aes_key_unwrap(kek, base64.b64decode(rows[0].wrapped_vmk))
        recovered_mek = aes_key_unwrap(recovered_vmk, base64.b64decode(persisted.wrapped_mek))
        assert (
            AESGCM(recovered_mek).decrypt(iv, base64.b64decode(persisted.ciphertext), None)
            == b"legacy fixture survives expansion"
        )
    db_engine.dispose()
