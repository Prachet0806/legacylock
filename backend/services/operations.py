from datetime import UTC, datetime

from models import WorkerCheckpoint


def checkpoint(factory, kind, error=None):
    with factory() as db:
        row = db.get(WorkerCheckpoint, kind)
        if row is None:
            row = WorkerCheckpoint(kind=kind)
            db.add(row)
        if error is None:
            row.last_success_at = datetime.now(UTC)
        row.last_error = error
        db.commit()
