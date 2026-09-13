from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv

from jobsearch.config.settings import get_settings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


def run_migrations(database_url: str | None = None) -> None:
    """Apply the Alembic migration chain for the configured schema.

    The explicit function argument wins over the environment-backed
    ``JOBSEARCH_DATABASE_URL`` setting. Both the app and Alembic paths
    consult the project .env file before selecting a URL.
    """
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    env_target = os.getenv("JOBSEARCH_DATABASE_URL")
    target_url = database_url or env_target or get_settings().database_url

    if target_url.startswith("sqlite:///./"):
        db_path = Path(target_url.replace("sqlite:///./", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).resolve().parents[3]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.attributes["database_url_override"] = target_url
    config.set_main_option("sqlalchemy.url", target_url.replace("%", "%%"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    run_migrations()
