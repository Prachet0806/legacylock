from sqlalchemy import (
    create_engine, Column, Integer, Text,
    ForeignKey, DateTime
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./legacylock.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Vault(Base):
    __tablename__ = "vault"

    id = Column(Integer, primary_key=True)
    messages = relationship("VaultMessage", back_populates="vault")


class VaultMessage(Base):
    __tablename__ = "vault_message"

    id = Column(Integer, primary_key=True)
    vault_id = Column(Integer, ForeignKey("vault.id"))
    label = Column(Text)
    encrypted_content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    vault = relationship("Vault", back_populates="messages")


def init_db():
    Base.metadata.create_all(bind=engine)
