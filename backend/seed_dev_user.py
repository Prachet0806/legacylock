"""Seed a dev owner user + vault for local development.

Usage (from repo root, with Postgres running and .env configured):
    cd backend
    venv\\Scripts\\python seed_dev_user.py user@example.com <password>

Refuses to run when ENVIRONMENT=production. Safe to re-run (idempotent).
"""

import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings  # noqa: E402
from db import SessionLocal, init_db  # noqa: E402
from models import User, Vault  # noqa: E402
from services.auth import hash_password  # noqa: E402


def main() -> int:
    settings = get_settings()
    if settings.environment == "production":
        print("Refusing to seed in production.", file=sys.stderr)
        return 1
    email = sys.argv[1] if len(sys.argv) > 1 else "owner@example.com"
    password = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass("Password (12+ chars): ")
    if len(password) < 12:
        print("Password must be 12+ characters.", file=sys.stderr)
        return 1

    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Created user {email}")
        else:
            print(f"User {email} already exists")
        vault = db.query(Vault).filter(Vault.user_id == user.id, Vault.is_primary == True).first()
        if not vault:
            vault = Vault(user_id=user.id, name="Primary Vault", is_primary=True)
            db.add(vault)
            db.commit()
            print("Created Primary Vault")
        else:
            print("Vault already exists")
    finally:
        db.close()
    print(f"Done. Log in at http://localhost:3000/ with {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
