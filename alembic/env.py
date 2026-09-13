from __future__ import annotations

import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.abspath("."))

load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

from jobsearch.models.base import Base
from jobsearch.models.job import Job
from jobsearch.models.job_evaluation import JobEvaluation
from jobsearch.models.application import Application
from jobsearch.models.processing_run import ProcessingRun
from jobsearch.models.applicant import Applicant

config = context.config

# Let direct Alembic commands consult the application environment override.
env_url = config.attributes.get("database_url_override") or os.getenv("JOBSEARCH_DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url.replace("%", "%%"))

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, compare_server_default=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
