from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
from jobsearch.models import DailyMetric, ProcessingRun, RequestAttempt, RequestBudgetWindow
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage import history_retention as retention, source_repository
from jobsearch.storage.budget_repository import BudgetRepository, eligible_at
from jobsearch.models import RequestBudget
from jobsearch.storage.source_repository import SourceRepository
from jobsearch.storage.database import get_session, close_session

NOW = datetime(2026, 9, 17, 12)


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "history.db"}'
    run_migrations(url)
    SourceRepository(url).configure({'name': 'usajobs', 'adapter_type': 'usajobs'})
    monkeypatch.setattr(source_repository, 'utcnow', lambda: NOW)
    return url


def seed(url, *, age=400, completed=True, outcome='success', future_retry=False):
    session = get_session(url)
    try:
        stamp = NOW - timedelta(days=age)
        run = ProcessingRun(source='usajobs', started_at=stamp, completed_at=stamp if completed else None,
            status='completed' if completed else 'running', records_seen=10, jobs_new=4,
            jobs_deduplicated=5, records_invalid=1, jobs_scored=0, ai_cost=0.25,
            collection_mode='live', pages_collected=1, invalid_reason_counts={'invalid_title': 1})
        session.add(run)
        session.flush()
        attempt = RequestAttempt(processing_run_id=run.id, source='usajobs', budget_name='usajobs',
            endpoint='https://data.usajobs.gov/api/search', reserved_at=stamp,
            completed_at=stamp if outcome != 'reserved' else None, outcome=outcome,
            next_allowed_at=NOW + timedelta(hours=1) if future_retry else stamp,
            response_bytes=100, records_returned=None, http_status=200)
        session.add(attempt)
        session.commit()
        return run.id, attempt.id
    finally:
        close_session(session)


def counts(url):
    session = get_session(url)
    try:
        return [session.query(model).count() for model in (ProcessingRun, RequestAttempt, DailyMetric)]
    finally:
        close_session(session)


def test_dry_run_rollup_idempotence_and_nulls(database):
    seed(database)
    seed(database)
    report = retention.retain_history(database, now=NOW)
    assert report['runs']['count'] == report['requests']['count'] == 2
    assert counts(database) == [2, 2, 0]
    retention.retain_history(database, now=NOW, apply=True, limit=1)
    assert counts(database) == [1, 1, 2]
    retention.retain_history(database, now=NOW, apply=True)
    retention.retain_history(database, now=NOW, apply=True)
    assert counts(database) == [0, 0, 2]
    session = get_session(database)
    try:
        rows = {row.kind: row for row in session.scalars(select(DailyMetric))}
        assert rows['run'].rows == 2 and rows['run'].totals['jobs_new'] == 8
        assert rows['run'].totals['ai_cost'] == 0.5
        assert rows['run'].totals['invalid_reason:invalid_title'] == 2
        assert rows['request'].totals['response_bytes'] == 200
        assert 'records_returned' not in rows['request'].totals
        assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
    finally:
        close_session(session)


def test_retains_active_windows_unknown_attempts_running_parents_and_backoff(database):
    seed(database, age=2)
    seed(database, completed=False)
    seed(database, outcome='reserved')
    seed(database, future_retry=True)
    session = get_session(database)
    try:
        session.add(RequestBudgetWindow(budget_name='usajobs', window_seconds=3*86400, max_requests=1))
        session.commit()
        before = eligible_at(session, session.get(RequestBudget, 'usajobs'), NOW)
    finally:
        close_session(session)
    report = retention.retain_history(database, request_days=1, run_days=1, now=NOW, apply=True)
    assert report['requests']['count'] == report['runs']['count'] == 0
    assert counts(database) == [4, 4, 0]
    session = get_session(database)
    try:
        assert eligible_at(session, session.get(RequestBudget, 'usajobs'), NOW) == before
    finally:
        close_session(session)


def test_rejects_new_budget_windows_covering_pruned_history(database):
    seed(database, age=2)
    retention.retain_history(database, request_days=1, now=NOW, apply=True)
    with pytest.raises(ValueError, match='pruned request history'):
        BudgetRepository(database).configure('usajobs', min_interval_seconds=2,
            windows=[{'window_seconds': 3*86400, 'max_requests': 1}])
    BudgetRepository(database).configure('usajobs', min_interval_seconds=2,
        windows=[{'window_seconds': 86400, 'max_requests': 1}])


def test_rollup_and_deletes_rollback_together(database, monkeypatch):
    seed(database)
    original = retention.rollup
    def fail(session, row, kind):
        original(session, row, kind)
        if kind == 'run':
            raise RuntimeError('simulated failure after request deletion')
    monkeypatch.setattr(retention, 'rollup', fail)
    with pytest.raises(RuntimeError):
        retention.retain_history(database, apply=True, now=NOW)
    assert counts(database) == [1, 1, 0]


def test_request_and_run_retention_are_independent(database):
    seed(database, age=200)
    report = retention.retain_history(database, apply=True, now=NOW)
    assert report['requests']['count'] == 1 and report['runs']['count'] == 0
    assert counts(database) == [1, 0, 1]


def test_populated_rollups_cannot_be_silently_downgraded(database):
    from alembic import command
    from alembic.config import Config
    seed(database)
    retention.retain_history(database, apply=True, now=NOW)
    config = Config('alembic.ini')
    config.attributes['database_url_override'] = database
    with pytest.raises(RuntimeError, match='Cannot downgrade'):
        command.downgrade(config, '20260916_15')
    assert counts(database) == [0, 0, 2]
