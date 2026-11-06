from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

settings = get_settings()
DATABASE_URL = settings.database_url


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = DATABASE_URL
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        # StaticPool is only correct for :memory: (one shared in-memory DB);
        # file-based SQLite must use a real pool so concurrent requests don't
        # corrupt a shared connection.
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models so metadata registers
    import app.models.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
