from __future__ import annotations

import os
from pathlib import Path

from jobsearch.scripts.run_fixture_ingestion import run_fixture_ingestion
from jobsearch.storage.database import SessionLocal, engine
from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun


def test_end_to_end_fixture_ingestion_writes_jobs_and_run() -> None:
    db_path = Path("data/test-jobsearch.db")
    if db_path.exists():
        db_path.unlink()

    os.environ["JOBSEARCH_DATABASE_URL"] = f"sqlite:///{db_path}"

    # Reload settings to see the environment-backed URL.
    from importlib import reload
    import jobsearch.config.settings as settings_module
    reload(settings_module)

    from jobsearch.config.settings import settings
    from jobsearch.storage import database as storage_module
    reload(storage_module)

    # the engine module object used by SessionLocal must refresh target config too
    fixture = Path("data/jobs_fixture.json")
    run_fixture_ingestion(fixture)

    session = SessionLocal()
    try:
        jobs = session.query(Job).count()
        processing_runs = session.query(ProcessingRun).count()
        assert jobs >= 2
        assert processing_runs == 1
    finally:
        session.close()
