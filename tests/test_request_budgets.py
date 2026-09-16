from datetime import datetime, timedelta
from io import BytesIO

import pytest
from alembic import command
from alembic.config import Config

from jobsearch.collectors import remotive_collector
from jobsearch.collectors.source import SourceSkipped
from jobsearch.ingestion.runner import run_collector
from jobsearch.models import RequestAttempt, RequestBudget
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage import source_repository
from jobsearch.storage.budget_repository import BudgetRepository
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.source_repository import SourceRepository


def test_board_refresh_does_not_delay_other_board(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'schedule.db'}"
    run_migrations(url)
    now = datetime(2026, 9, 15, 12)
    monkeypatch.setattr(source_repository, "utcnow", lambda: now)
    monkeypatch.setattr(remotive_collector, "urlopen", lambda *a, **k: BytesIO(b'{"jobs":[]}'))
    repo = SourceRepository(url)
    for name in ('a', 'b'):
        repo.configure({'name': name, 'adapter_type': 'remotive', 'refresh_interval_seconds': 43200})
    assert run_collector('a', database_url=url).status == 'completed'
    assert repo.get('a').next_due_at == now + timedelta(hours=12)
    now += timedelta(hours=6)
    assert run_collector('a', database_url=url).skip_reason == 'Collector refresh is not due'
    assert run_collector('b', database_url=url).status == 'completed'
    assert repo.get('a').request_attempts == repo.get('b').request_attempts == 1


def test_multiple_rolling_windows_and_backoff(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'windows.db'}"
    run_migrations(url)
    now = datetime(2026, 9, 15, 12)
    monkeypatch.setattr(source_repository, 'utcnow', lambda: now)
    repo = SourceRepository(url)
    for name in ('a', 'b'):
        repo.configure({'name': name, 'adapter_type': 'remotive'})
    BudgetRepository(url).configure('remotive', min_interval_seconds=21600,
        windows=[{'window_seconds': 86400, 'max_requests': 2},
                 {'window_seconds': 172800, 'max_requests': 3}])
    repo.reserve('a')  # Unfinished requests consume quota, too.
    now += timedelta(hours=6)
    repo.reserve('b')
    now += timedelta(hours=6)
    with pytest.raises(SourceSkipped) as exc:
        repo.reserve('a')
    assert exc.value.next_allowed_at == datetime(2026, 9, 16, 12)
    now = exc.value.next_allowed_at
    repo.reserve('a')
    now += timedelta(hours=6)
    with pytest.raises(SourceSkipped) as exc:
        repo.reserve('b')
    assert exc.value.next_allowed_at == datetime(2026, 9, 17, 12)
    # Removing a rule does not erase an already-active wait.
    BudgetRepository(url).configure('remotive', min_interval_seconds=21600, windows=[])
    with pytest.raises(SourceSkipped):
        repo.reserve('b')


def test_migration_preserves_rows_and_disabled_wait(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    cfg = Config('alembic.ini')
    cfg.attributes['database_url_override'] = url
    command.upgrade(cfg, '20260915_11')
    session = get_session(url)
    try:
        session.connection().exec_driver_sql("""INSERT INTO job_sources
            (name,adapter_type,enabled,settings,endpoint,collection_strategy,response_retention,
             min_interval_seconds,request_attempts,next_allowed_at)
            VALUES ('old','remotive',0,'{}','https://remotive.com/api/remote-jobs',
                    'full_feed','none',21600,7,'2026-09-20 12:00:00')""")
        session.connection().exec_driver_sql("""INSERT INTO processing_runs
            (id,started_at,source,status,records_seen,jobs_new,jobs_deduplicated,records_invalid,jobs_scored)
            VALUES (1,'2026-09-15 12:00:00','old','completed',0,0,0,0,0)""")
        session.connection().exec_driver_sql("""INSERT INTO request_attempts
            (id,processing_run_id,source,endpoint,reserved_at,outcome,next_allowed_at,http_status)
            VALUES (1,1,'old','https://remotive.com/api/remote-jobs','2026-09-15 12:00:00',
                    'http_error','2026-09-20 12:00:00',429)""")
        session.commit()
        before = session.connection().exec_driver_sql('SELECT * FROM job_sources').all()
        attempts_before = session.connection().exec_driver_sql('SELECT * FROM request_attempts').all()
    finally:
        close_session(session)
    command.upgrade(cfg, 'head')
    session = get_session(url)
    try:
        budget = session.get(RequestBudget, 'remotive')
        assert budget.next_allowed_at == datetime(2026, 9, 20, 12)
        attempt = session.query(RequestAttempt).one()
        assert attempt.budget_name == 'remotive' and attempt.processing_run_id == 1 and attempt.http_status == 429
        assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
    finally:
        close_session(session)
    command.downgrade(cfg, '20260915_11')
    session = get_session(url)
    try:
        assert session.connection().exec_driver_sql('SELECT * FROM job_sources').all() == before
        assert session.connection().exec_driver_sql('SELECT * FROM request_attempts').all() == attempts_before
    finally:
        close_session(session)
