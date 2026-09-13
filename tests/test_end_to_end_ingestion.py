from __future__ import annotations

from importlib import reload
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import jobsearch.config.settings as settings_module
import jobsearch.scripts.run_fixture_ingestion as ingestion_module
from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun
from jobsearch.storage.database import close_session, get_session


def test_end_to_end_fixture_ingestion_writes_jobs_and_run(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "jobsearch.db"
        monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{tmp_db}")

        reload(settings_module)
        reload(ingestion_module)

        fixture = Path("data/jobs_fixture.json")
        inserted_count = ingestion_module.run_fixture_ingestion(fixture)

        session = get_session(f"sqlite:///{tmp_db}")
        try:
            jobs = session.query(Job).count()
            processing_runs = session.query(ProcessingRun).all()

            assert inserted_count == 2
            assert jobs == 2
            assert len(processing_runs) == 1

            run = processing_runs[0]
            assert run.source == "fixture_json"
            assert run.status == "completed"
            assert run.error_message is None
            assert run.jobs_seen == 2
            assert run.jobs_new == 2
            assert run.jobs_deduplicated == 0
            assert run.jobs_filtered == 0
            assert run.jobs_scored == 0
            assert run.ai_cost == 0
        finally:
            close_session(session)


def test_repeated_fixture_ingestion_is_idempotent_from_db_deduplication(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "jobsearch.db"
        monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{tmp_db}")

        reload(settings_module)
        reload(ingestion_module)

        fixture = Path("data/jobs_fixture.json")
        first_return = ingestion_module.run_fixture_ingestion(fixture)
        second_return = ingestion_module.run_fixture_ingestion(fixture)

        session = get_session(f"sqlite:///{tmp_db}")
        try:
            jobs = session.query(Job).count()
            processing_runs = session.query(ProcessingRun).count()
            assert first_return == 2
            assert second_return == 0
            assert jobs == 2
            assert processing_runs == 2
        finally:
            close_session(session)


def test_fixture_ingestion_deduplicates_duplicates_within_a_single_batch(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "jobsearch.db"
        monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{tmp_db}")

        reload(settings_module)
        reload(ingestion_module)

        fixture = Path("data/jobs_fixture_with_duplicates.json")
        inserted_count = ingestion_module.run_fixture_ingestion(fixture)

        session = get_session(f"sqlite:///{tmp_db}")
        try:
            jobs = session.query(Job).count()
            processing_runs = session.query(ProcessingRun).all()
            assert inserted_count == 2
            assert jobs == 2
            assert processing_runs[0].jobs_deduplicated == 1
        finally:
            close_session(session)


def test_filter_counts_are_recorded_in_processing_run_metrics(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "jobsearch.db"
        monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{tmp_db}")

        reload(settings_module)
        reload(ingestion_module)

        fixture = Path("data/jobs_fixture_with_filtered.json")
        inserted_count = ingestion_module.run_fixture_ingestion(fixture)

        session = get_session(f"sqlite:///{tmp_db}")
        try:
            runs = session.query(ProcessingRun).all()
            assert inserted_count == 1
            assert runs[0].jobs_seen == 3
            assert runs[0].jobs_new == 1
            assert runs[0].jobs_filtered == 2
        finally:
            close_session(session)


def test_missing_source_ids_do_not_bypass_deduplication_and_are_not_inserted(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "jobsearch.db"
        monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{tmp_db}")

        reload(settings_module)
        reload(ingestion_module)

        fixture = Path("data/jobs_fixture_missing_source_id.json")
        inserted_count = ingestion_module.run_fixture_ingestion(fixture)

        session = get_session(f"sqlite:///{tmp_db}")
        try:
            jobs = session.query(Job).count()
            runs = session.query(ProcessingRun).all()
            assert inserted_count == 0
            assert jobs == 0
            assert runs[0].jobs_seen == 2
            assert runs[0].jobs_filtered == 2
        finally:
            close_session(session)


def test_failed_fixture_ingestion_persists_processing_run_failure_status(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "jobsearch.db"
        monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{tmp_db}")

        reload(settings_module)
        reload(ingestion_module)

        def broken_collect(self):
            raise ValueError("boom")

        monkeypatch.setattr(ingestion_module.JsonFixtureCollector, "collect", broken_collect)

        with pytest.raises(ValueError, match="boom"):
            ingestion_module.run_fixture_ingestion(Path("data/jobs_fixture.json"))

        session = get_session(f"sqlite:///{tmp_db}")
        try:
            runs = session.query(ProcessingRun).all()
            assert len(runs) == 1
            assert runs[0].status == "failed"
            assert runs[0].error_message == "boom"
            assert runs[0].jobs_new == 0
            assert runs[0].jobs_seen == 0
        finally:
            close_session(session)
