from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from jobsearch.config.settings import get_settings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


def run_migrations(database_url: str | None = None) -> None:
    """Apply the Alembic migration chain for the configured schema.

    This is the only supported schema management route for v1. It replaces
    the old metadata.create_all() bootstrap that bypassed versioned migrations.
    """
    target_url = database_url or get_settings().database_url
    if target_url.startswith("sqlite:///./"):
        db_path = Path(target_url.replace("sqlite:///./", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", target_url)
    command.upgrade(config, "head")


if __name__ == "__main__":
    run_migrations(get_settings().database_url)
