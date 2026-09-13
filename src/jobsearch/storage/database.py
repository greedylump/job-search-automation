from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from jobsearch.config.settings import settings
from jobsearch.models.base import Base

logger = logging.getLogger(__name__)


engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(database_url: str | None = None) -> None:
    """Create all tables for the initial schema using SQLAlchemy metadata."""
    target_url = database_url or settings.database_url
    if target_url.startswith("sqlite:///./"):
        db_path = Path(target_url.replace("sqlite:///./", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine_for_creation = create_engine(target_url, future=True)
    Base.metadata.create_all(bind=engine_for_creation)
    logger.info("Initialized database schema at %s", target_url)


def get_session() -> Session:
    """Return a SQLAlchemy session for repository operations."""
    return SessionLocal()
