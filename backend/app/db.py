"""SQLite engine + session helpers. Single-file store is deliberate for the MVP;
swapping `DATABASE_URL` to Postgres is the only change needed to scale out."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import DATA_DIR, get_settings
from .models import domain as _domain  # noqa: F401  (register tables)
from .models import errors as _errors  # noqa: F401

_engine: Engine | None = None


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    # The CLI runner and the API server share one file. Without a bounded busy
    # timeout a writer can block on the other process indefinitely; with it,
    # contention surfaces as an error we can see instead of a silent hang.
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            get_settings().database_url,
            connect_args={"check_same_thread": False},
        )
    return _engine


def init_db(engine: Engine | None = None) -> Engine:
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    with Session(engine or get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine()) as session:
        yield session
