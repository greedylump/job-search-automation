from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

import jobsearch.config.settings as settings_module
import jobsearch.scripts.run_fixture_ingestion as ingestion_module
from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun
from jobsearch.storage.database import get_session


def test_end_to_end_fixture_ingestion_writes_jobs_and_run() -> None:
    db_path = Path("data/test-jobsearch.db")
    if db_path.exists():
        db_path.unlink()

    os.environ["JOBSEARCH_DATABASE_URL"] = f"sqlite:///{db_path}"

    # Refresh the settings module and import the script module after the URL is updated.
    reload(settings_module)
    reload(ingestion_module)

    fixture = Path("data/jobs_fixture.json")
    inserted_count = ingestion_module.run_fixture_ingestion(fixture)

    session = get_session(f"sqlite:///{db_path}")
    try:
        jobs = session.query(Job).count()
        processing_runs = session.query(ProcessingRun).all()

        assert inserted_count == 2
        assert jobs == 2
        assert len(processing_runs) == 1

        run = processing_runs[0]
        assert run.source == "fixture_json"
        assert run.jobs_seen == 2
        assert run.jobs_new == 2
        assert run.jobs_deduplicated == 0
        assert run.jobs_filtered == 0
        assert run.jobs_scored == 0
        assert run.ai_cost == 0
    finally:
        session.close()
