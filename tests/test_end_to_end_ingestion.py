from __future__ import annotations

from importlib import reload
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import jobsearch.config.settings as settings_module
import jobsearch.scripts.run_fixture_ingestion as ingestion_module
from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun
from jobsearch.storage.database import close_session, get_session
from jobsearch.collectors.json_fixture_collector import JsonFixtureCollector


@pytest.mark.parametrize("wrapped", [False, True])
def test_malformed_entries_are_counted_without_losing_valid_jobs(tmp_path, monkeypatch, wrapped, caplog):
    caplog.set_level("INFO", logger=ingestion_module.__name__)
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", database_url)
    entries = [
        {"source_job_id": "first", "title": "Engineer"},
        "unexpected text", None, 42, True, ["unexpected array"],
        *[{"source_job_id": f"bad-{index}", "title": title}
          for index, title in enumerate([42, True, [], {}, None, "", " ", "x"])],
        {},
        {"source_job_id": "second", "title": "Developer"},
        {"source_job_id": "first", "title": "Engineer"},
    ]
    fixture = tmp_path / "mixed.json"
    fixture.write_text(json.dumps({"jobs": entries} if wrapped else entries), encoding="utf-8")
    assert JsonFixtureCollector(fixture).collect() == entries

    for expected_new, expected_deduplicated in [(2, 1), (0, 3)]:
        assert ingestion_module.run_fixture_ingestion(fixture) == expected_new
        session = get_session(database_url)
        try:
            assert {job.source_job_id for job in session.query(Job)} == {"first", "second"}
            run = session.query(ProcessingRun).order_by(ProcessingRun.id.desc()).first()
            assert run.status == "completed" and run.error_message is None
            assert run.records_seen == len(entries)
            assert run.jobs_new == expected_new
            assert run.jobs_deduplicated == expected_deduplicated
            assert run.records_invalid == 14
            assert run.invalid_reason_counts == {"non_object": 5, "missing_source_id": 1, "invalid_title": 8}
            assert sum(run.invalid_reason_counts.values()) == run.records_invalid
            assert "Invalid records: non-object=5; missing ID=1; invalid title=8" in caplog.text
            assert run.records_seen == run.jobs_new + run.jobs_deduplicated + run.records_invalid
            assert run.jobs_scored == 0 and run.ai_cost == 0
            assert run.started_at <= run.completed_at
        finally:
            close_session(session)


@pytest.mark.parametrize("contents", ['{', '{"jobs": "invalid"}', 'null'])
def test_invalid_fixture_structure_records_failed_run(tmp_path, monkeypatch, contents):
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", database_url)
    fixture = tmp_path / "invalid.json"
    fixture.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        ingestion_module.run_fixture_ingestion(fixture)
    session = get_session(database_url)
    try:
        assert session.query(Job).count() == 0
        run = session.query(ProcessingRun).one()
        assert run.status == "failed" and run.error_message
        assert run.records_seen == run.jobs_new == run.records_invalid == 0
        assert run.invalid_reason_counts == {"non_object": 0, "missing_source_id": 0, "invalid_title": 0}
        assert run.completed_at is not None
    finally:
        close_session(session)


def test_invalid_reason_counts_survive_insert_rollback(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    database_url = f"sqlite:///{tmp_path / 'failure.db'}"
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", database_url)
    fixture = tmp_path / "mixed.json"
    fixture.write_text(json.dumps([None, {}, {"id": "bad", "title": 42},
                                   {"id": "good", "title": "Engineer"}]), encoding="utf-8")

    def fail_insert(session, flush_context, instances):
        if any(isinstance(obj, Job) for obj in session.new):
            raise ValueError("insert failed")

    event.listen(Session, "before_flush", fail_insert)
    try:
        with pytest.raises(ValueError, match="insert failed"):
            ingestion_module.run_fixture_ingestion(fixture)
    finally:
        event.remove(Session, "before_flush", fail_insert)
    session = get_session(database_url)
    try:
        run = session.query(ProcessingRun).one()
        assert run.status == "failed" and run.jobs_new == 0
        assert session.query(Job).count() == 0
        assert run.invalid_reason_counts == {"non_object": 1, "missing_source_id": 1, "invalid_title": 1}
        assert sum(run.invalid_reason_counts.values()) == run.records_invalid == 3
    finally:
        close_session(session)


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
            assert run.records_seen == 2
            assert run.jobs_new == 2
            assert run.jobs_deduplicated == 0
            assert run.records_invalid == 0
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
            assert inserted_count == 2
            assert runs[0].records_seen == 3
            assert runs[0].jobs_new == 2
            assert runs[0].records_invalid == 1
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
            assert runs[0].records_seen == 2
            assert runs[0].records_invalid == 2
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
            assert runs[0].records_seen == 0
        finally:
            close_session(session)
