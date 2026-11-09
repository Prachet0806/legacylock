"""Measure one idle delivery cycle against a disposable migrated SQLite DB.

This is a repeatable local baseline, not a substitute for hosted PostgreSQL or
container CPU/memory qualification. Run with the backend virtualenv Python.
"""

import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path


def main() -> None:
    backend_dir = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="legacylock-idle-bench-") as temp_dir:
        db_file = Path(temp_dir) / "bench.db"
        os.environ.update(
            ENVIRONMENT="test",
            SESSION_SECRET="benchmark-only-secret-0123456789abcdef",
            DATABASE_URL=f"sqlite:///{db_file.as_posix()}",
            SQLITE_FILE=str(db_file),
            DELIVERY_ENABLED="true",
            JWT_PRIVATE_KEY_PATH=str(backend_dir / "keys" / "jwt_private.pem"),
            JWT_PUBLIC_KEY_PATH=str(backend_dir / "keys" / "jwt_public.pem"),
        )

        from alembic import command
        from alembic.config import Config

        migration = Config(str(backend_dir / "alembic.ini"))
        migration.set_main_option("script_location", str(backend_dir / "alembic"))
        command.upgrade(migration, "head")

        from sqlalchemy import event

        from db import SessionLocal, engine
        from services.operations import checkpoint
        from services.outbox import work_once

        statement_counts: Counter[str] = Counter()
        sql_seconds = 0.0

        def before_execute(conn, cursor, statement, parameters, context, executemany):
            context._bench_started = time.perf_counter()

        def after_execute(conn, cursor, statement, parameters, context, executemany):
            nonlocal sql_seconds
            sql_seconds += time.perf_counter() - context._bench_started
            statement_counts[statement.lstrip().split(None, 1)[0].upper()] += 1

        event.listen(engine, "before_cursor_execute", before_execute)
        event.listen(engine, "after_cursor_execute", after_execute)

        samples = []
        for _ in range(5):
            before = time.perf_counter()
            jobs = work_once(SessionLocal)
            checkpoint(SessionLocal, "delivery")
            samples.append({"jobs": jobs, "wall_ms": round((time.perf_counter() - before) * 1000, 2)})

        print(json.dumps({
            "mode": "sqlite_idle_worker_cycle",
            "samples": samples,
            "sql_statements": dict(statement_counts),
            "sql_ms_total": round(sql_seconds * 1000, 2),
            "duration_ms_total": round(sum(sample["wall_ms"] for sample in samples), 2),
        }, indent=2))
        engine.dispose()


if __name__ == "__main__":
    main()
