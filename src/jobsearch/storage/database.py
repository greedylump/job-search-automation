from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from jobsearch.config.settings import get_settings


def _configure_sqlite(engine: Engine) -> Engine:
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def build_session_factory(database_url: str | None = None):
    target_url = database_url or get_settings().database_url
    if target_url.startswith("sqlite"):
        engine = _configure_sqlite(create_engine(target_url, future=True, connect_args={"check_same_thread": False}))
    else:
        engine = create_engine(target_url, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session(database_url: str | None = None) -> Session:
    """Return a SQLAlchemy session for repository operations using the current environment URL."""
    session_factory = build_session_factory(database_url)
    return session_factory()


def close_session(session: Session | None) -> None:
    if session is None:
        return
    try:
        session.close()
    finally:
        bind = session.get_bind()
        if bind is not None:
            try:
                bind.dispose()
            except Exception:
                pass


def get_session_factory(database_url: str | None = None):
    return build_session_factory(database_url)
