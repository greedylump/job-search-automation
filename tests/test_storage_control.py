import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobsearch.collectors.http_client import fetch_records
from jobsearch.collectors.http_request import RequestSpec
from jobsearch.collectors.source import REMOTIVE, SourceSkipped
from jobsearch.ingestion.pipeline import run_ingestion
from jobsearch.ingestion.worker import run_due
from jobsearch.models import Job, ProcessingRun, RequestAttempt
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage import collection_control as guard
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.maintenance import snapshots
from jobsearch.storage.source_repository import SourceRepository


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBSEARCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(guard.shutil, 'disk_usage', lambda p: SimpleNamespace(free=20_000_000_000))
    url = f'sqlite:///{tmp_path / "storage.db"}'
    run_migrations(url)
    return url


def test_independent_disk_floor_persists_until_safe_resume(storage, monkeypatch):
    monkeypatch.setattr(guard.shutil, 'disk_usage', lambda p: SimpleNamespace(free=4_999_999_999))
    report = guard.control(storage)
    assert report['reason'] == 'disk_free_below_minimum'
    assert report['app_bytes'] < report['limits']['STORAGE_MAX_BYTES']
    assert guard.control(storage, 'resume')['paused']
    monkeypatch.setattr(guard.shutil, 'disk_usage', lambda p: SimpleNamespace(free=20_000_000_000))
    assert guard.control(storage)['paused']
    assert not guard.control(storage, 'resume')['paused']


def test_app_limit_counts_extra_directories_and_deduplicates(storage, tmp_path, monkeypatch):
    before = guard.measure(storage)['app_bytes']
    nested = tmp_path / 'snapshots'
    nested.mkdir()
    (nested / 'response.json').write_bytes(b'x' * 2000)
    monkeypatch.setenv('JOBSEARCH_STORAGE_DIRS', f'["{nested.as_posix()}"]')
    assert guard.measure(storage)['app_bytes'] == before + 2000
    monkeypatch.setenv('JOBSEARCH_STORAGE_MAX_BYTES', str(before + 1000))
    monkeypatch.setenv('JOBSEARCH_STORAGE_WARN_BYTES', '1')
    assert guard.control(storage)['reason'] == 'app_storage_limit_reached'


def test_pause_blocks_http_and_worker_without_attempt_or_run_spam(storage):
    guard.control(storage, 'pause')
    for _ in range(3):
        assert run_due(storage) == ([], {})
    with pytest.raises(SourceSkipped, match='manual_pause'):
        fetch_records(source=REMOTIVE, state=SourceRepository(storage),
            build_request=lambda c: RequestSpec(c.endpoint), decode=lambda raw: [],
            opener=lambda *a, **kw: pytest.fail('HTTP must not run'),
            now=datetime.now, max_bytes=100)
    session = get_session(storage)
    try:
        assert session.query(RequestAttempt).count() == 0
        assert session.query(ProcessingRun).count() == 0
    finally:
        close_session(session)


def test_pause_after_fetch_prevents_batch_write_records_reason(storage):
    def collect():
        guard.control(storage, 'pause')
        return [{'id': '1', 'title': 'Engineer'}]
    run = run_ingestion(source='test', collect=collect,
        normalize=lambda p: pytest.fail('Paused batch must not normalize'), database_url=storage)
    assert run.status == 'paused'
    assert 'manual_pause' in run.skip_reason
    assert run.jobs_new == 0
    session = get_session(storage)
    try:
        assert session.query(Job).count() == 0
    finally:
        close_session(session)


def test_measurement_failure_fails_closed(storage, monkeypatch):
    def fail(*args):
        raise PermissionError('Cannot inspect storage')
    monkeypatch.setattr(guard.shutil, 'disk_usage', fail)
    assert guard.control(storage)['reason'] == 'storage_check_failed'
    assert guard.control(storage, 'resume')['paused']


def test_cli_pause_status_resume(storage, capsys):
    import json
    from jobsearch.scripts.storage_cli import main
    for action, expected in [('pause', 2), ('status', 2), ('resume', 0), ('status', 0)]:
        assert main(['--database-url', storage, action]) == expected
        report = json.loads(capsys.readouterr().out)
        assert report['paused'] == (expected == 2)


def test_warning_does_not_pause_or_repeat(storage, monkeypatch, caplog):
    monkeypatch.setattr(guard.shutil, 'disk_usage', lambda p: SimpleNamespace(free=6_000_000_000))
    for _ in range(3):
        report = guard.control(storage)
        assert report['warning'] and not report['paused']
    assert sum('Storage warning:' in r.message for r in caplog.records) == 1


def test_untracked_snapshot_rejected_before_network(storage, tmp_path):
    with pytest.raises(ValueError, match='tracked storage directory'):
        fetch_records(source=REMOTIVE, state=SourceRepository(storage),
            build_request=lambda c: RequestSpec(c.endpoint), decode=lambda raw: [],
            opener=lambda *a, **kw: pytest.fail('HTTP must not run'),
            now=datetime.now, max_bytes=100, snapshot_path=tmp_path.parent / 'untracked-response.json')


def test_snapshot_retention_dry_run_and_apply(tmp_path):
    old = tmp_path / 'old.json'
    old.write_text('{}')
    fresh = tmp_path / 'fresh.json'
    fresh.write_text('{}')
    db = tmp_path / 'keep.db'
    db.write_bytes(b'database')
    os.utime(old, (1, 1))
    os.utime(db, (1, 1))
    plan = snapshots(tmp_path)
    assert [p['path'] for p in plan] == [str(old.resolve())]
    assert old.exists()
    assert snapshots(tmp_path, apply=True) == plan
    assert not old.exists() and fresh.exists() and db.exists()


def test_retention_rejects_relative_path_to_filesystem_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    relative_root = Path(*(['..'] * (len(tmp_path.parts) - 1)))
    with pytest.raises(ValueError, match='filesystem root'):
        snapshots(relative_root)


def test_collector_status_explains_global_pause(storage, capsys):
    from jobsearch.scripts.collector_status import print_status
    guard.control(storage, 'pause')
    print_status(storage, None, 10)
    output = capsys.readouterr().out
    assert 'Global collection: PAUSED' in output
    assert 'manual_pause' in output
