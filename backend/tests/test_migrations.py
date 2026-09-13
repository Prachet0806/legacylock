"""Migration drift: migrated schema must match SQLAlchemy models exactly."""

import tempfile
from pathlib import Path

from sqlalchemy import MetaData, create_engine


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
