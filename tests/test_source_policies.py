from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from jobsearch.collectors import remotive_collector
from jobsearch.collectors.source import REMOTIVE, SourceSkipped
from jobsearch.models import Job, JobSource
from jobsearch.scripts.init_db import run_migrations
from jobsearch.scripts.run_remotive_ingestion import run_remotive_ingestion
from jobsearch.storage import source_repository
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.source_repository import SourceRepository

SAMPLE = Path(__file__).resolve().parents[1] / "data/remotive_sample.json"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'state.db'}"
    now = datetime(2026, 9, 14, 12)
    monkeypatch.setattr(source_repository, "utcnow", lambda: now)
    monkeypatch.setattr(remotive_collector, "utcnow", lambda: now)
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        return BytesIO(SAMPLE.read_bytes())
    monkeypatch.setattr(remotive_collector, "urlopen", fetch)
    return url, now, calls


def test_interval_boundary_and_no_automatic_files(setup, monkeypatch, tmp_path):
    url, now, calls = setup
    monkeypatch.setenv("JOBSEARCH_DATA_DIR", str(tmp_path / "unused-cache"))
    run_remotive_ingestion(database_url=url)
    monkeypatch.setattr(source_repository, "utcnow", lambda: now + timedelta(hours=6) - timedelta(seconds=1))
    assert run_remotive_ingestion(database_url=url).status == "skipped"
    monkeypatch.setattr(source_repository, "utcnow", lambda: now + timedelta(hours=6))
    assert run_remotive_ingestion(database_url=url).jobs_deduplicated == 2
    assert len(calls) == 2 and not (tmp_path / "unused-cache").exists()


@pytest.mark.parametrize("header", ["43200", "Tue, 15 Sep 2026 00:00:00 GMT"])
def test_retry_after_extends_reservation(setup, monkeypatch, header):
    url, now, calls = setup
    def fail(*args, **kwargs):
        calls.append(1)
        raise HTTPError(REMOTIVE.endpoint, 429, "limited", {"Retry-After": header}, None)
    monkeypatch.setattr(remotive_collector, "urlopen", fail)
    with pytest.raises(RuntimeError):
        run_remotive_ingestion(database_url=url)
    monkeypatch.setattr(source_repository, "utcnow", lambda: now + timedelta(hours=7))
    skipped = run_remotive_ingestion(database_url=url)
    assert skipped.status == "skipped" and skipped.next_eligible_at == now + timedelta(hours=12)
    assert len(calls) == 1
    session = get_session(url)
    try:
        state = session.get(JobSource, "remotive")
        assert state.last_http_status == 429 and state.last_success_at is None
        assert state.request_attempts == 1
    finally:
        close_session(session)


def test_concurrent_reservations_allow_only_one_request(setup):
    url, _, _ = setup
    run_migrations(url)
    def claim(_):
        try:
            SourceRepository(url).reserve(REMOTIVE)
            return "reserved"
        except SourceSkipped:
            return "skipped"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == ["reserved", "skipped"]


def test_explicit_replay_does_not_touch_request_state_or_freshness(setup, tmp_path):
    url, _, calls = setup
    snapshot = tmp_path / "snapshot.json"
    run_remotive_ingestion(database_url=url, snapshot_path=snapshot)
    session = get_session(url)
    try:
        before = [(job.id, job.last_seen_at) for job in session.query(Job).order_by(Job.id)]
        allowed = session.get(JobSource, "remotive").next_allowed_at
    finally:
        close_session(session)
    replay = run_remotive_ingestion(database_url=url, replay_path=snapshot)
    assert replay.collection_mode == "replay" and replay.jobs_deduplicated == 2
    session = get_session(url)
    try:
        assert [(job.id, job.last_seen_at) for job in session.query(Job).order_by(Job.id)] == before
        state = session.get(JobSource, "remotive")
        assert state.request_attempts == 1 and state.next_allowed_at == allowed
    finally:
        close_session(session)
    assert len(calls) == 1


def test_not_modified_records_check_without_ingesting(setup, monkeypatch):
    url, now, _ = setup
    def unchanged(*args, **kwargs):
        raise HTTPError(REMOTIVE.endpoint, 304, "Not Modified", {}, None)
    monkeypatch.setattr(remotive_collector, "urlopen", unchanged)
    run = run_remotive_ingestion(database_url=url)
    assert run.status == "not_modified" and run.records_seen == run.jobs_new == 0
    session = get_session(url)
    try:
        state = session.get(JobSource, "remotive")
        assert state.last_success_at == now and state.last_http_status == 304
    finally:
        close_session(session)


def test_upgrade_keeps_legacy_metrics_and_conservatively_initializes_policy(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from jobsearch.models import ProcessingRun

    url = f"sqlite:///{tmp_path / 'old.db'}"
    config = Config(str(SAMPLE.parents[1] / "alembic.ini"))
    config.attributes["database_url_override"] = url
    command.upgrade(config, "20260914_08")
    session = get_session(url)
    try:
        session.connection().exec_driver_sql(
            "INSERT INTO processing_runs (started_at,source,records_seen,jobs_new,jobs_deduplicated,records_invalid,jobs_scored,ai_cost,status) "
            "VALUES ('2026-09-14 12:00:00','remotive',16,16,0,0,0,0,'completed')"
        )
        session.commit()
    finally:
        close_session(session)
    command.upgrade(config, "head")
    session = get_session(url)
    try:
        run = session.query(ProcessingRun).one()
        assert run.jobs_new == run.records_seen == 16 and run.collection_mode is None
        state = session.get(JobSource, "remotive")
        assert state.next_allowed_at == datetime(2026, 9, 14, 18)
        assert state.last_attempt_at is state.last_success_at is None
        assert state.request_attempts == 0
    finally:
        close_session(session)
    command.downgrade(config, "20260914_08")
    session = get_session(url)
    try:
        assert "job_sources" not in inspect(session.connection()).get_table_names()
        assert session.connection().exec_driver_sql("SELECT records_seen,jobs_new FROM processing_runs").one() == (16, 16)
    finally:
        close_session(session)


@pytest.mark.parametrize("header", ["nonsense", "-30", "0", "1", "Mon, 14 Sep 2026 10:00:00 GMT"])
def test_retry_after_never_shortens_policy_interval(setup, monkeypatch, header):
    url, now, _ = setup
    def fail(*args, **kwargs):
        raise HTTPError(REMOTIVE.endpoint, 503, "Unavailable", {"Retry-After": header}, None)
    monkeypatch.setattr(remotive_collector, "urlopen", fail)
    with pytest.raises(RuntimeError):
        run_remotive_ingestion(database_url=url)
    assert run_remotive_ingestion(database_url=url).next_eligible_at == now + timedelta(hours=6)


def test_snapshot_existing_path_fails_without_consuming_request(setup, tmp_path):
    url, _, calls = setup
    path = tmp_path / "snapshot.json"
    path.write_text("keep this", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_remotive_ingestion(database_url=url, snapshot_path=path)
    assert path.read_text() == "keep this" and calls == []
