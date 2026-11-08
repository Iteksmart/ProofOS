from __future__ import annotations

import os
from pathlib import Path

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

    if not settings.is_prod:
        # Convenient local/test setup; production schema is managed by Alembic.
        Base.metadata.create_all(bind=engine)
        return

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    alembic_config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(alembic_config)
    expected = scripts.get_current_head()
    with engine.connect() as connection:
        actual = MigrationContext.configure(connection).get_current_revision()
    if actual != expected:
        raise RuntimeError(
            f"Database schema revision {actual or 'unversioned'} does not match application head {expected}; "
            "run `python -m alembic upgrade head` before starting ProofOS."
        )


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
