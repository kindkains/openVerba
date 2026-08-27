"""Engine und Session-Factory."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _create_engine():
    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # In-Memory-SQLite der Tests muss über Threads hinweg dieselbe Verbindung sehen.
        from sqlalchemy.pool import StaticPool

        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_recycle"] = 3600
    return create_engine(url, **kwargs)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI-Dependency: eine Session pro Request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
