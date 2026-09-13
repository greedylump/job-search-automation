from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from jobsearch.config.settings import get_settings


def build_session_factory(database_url: str | None = None):
    target_url = database_url or get_settings().database_url
    engine = create_engine(target_url, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session(database_url: str | None = None) -> Session:
    """Return a SQLAlchemy session for repository operations using the current environment URL."""
    session_factory = build_session_factory(database_url)
    return session_factory()


def get_session_factory(database_url: str | None = None):
    return build_session_factory(database_url)
