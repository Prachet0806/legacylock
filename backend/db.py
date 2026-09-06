from config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Alembic owns schema in production; create_all only for dev/test convenience.
    if settings.environment == "production":
        return
    Base.metadata.create_all(bind=engine)