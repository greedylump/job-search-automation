import json
from io import BytesIO
from pathlib import Path

import pytest

from jobsearch.collectors import remotive_collector
from jobsearch.ingestion.runner import run_collector, run_enabled
from jobsearch.models import Job, JobSource, ProcessingRun
from jobsearch.scripts.collectors_cli import main
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.source_repository import SourceRepository
from jobsearch.storage.database import get_session, close_session

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def database(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("No live API calls in tests")
    monkeypatch.setattr(remotive_collector, "urlopen", no_network)
    url = f"sqlite:///{tmp_path / 'instances.db'}"
    run_migrations(url)
    return url, SourceRepository(url)


def fixture_config(name, path, **changes):
    return {"name": name, "adapter_type": "json_fixture", "settings": {"path": str(path)}, **changes}


def test_mutable_instances_and_run_enabled(database, tmp_path):
    url, repo = database
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps([{"id": "one", "title": "Engineer"}]))
    second.write_text(json.dumps([{"id": "two", "title": "Developer"}]))
    repo.configure(fixture_config("a", first))
    repo.configure(fixture_config("b", second, enabled=False))
    results, errors = run_enabled(database_url=url)
    assert not errors and [(r.source, r.jobs_new) for r in results] == [("a", 1)]
    assert run_collector("b", database_url=url).status == "skipped"
    repo.configure({"settings": {"path": str(second)}}, name="a")
    repo.configure({"enabled": True}, name="b")
    results, errors = run_enabled(database_url=url)
    assert not errors and [(r.source, r.jobs_new) for r in results] == [("a", 1), ("b", 1)]
    session = get_session(url)
    try:
        assert session.query(Job).count() == 3
        assert all(c.request_attempts == 0 for c in session.query(JobSource))
        assert {j.source for j in session.query(Job)} == {"a", "b"}
    finally:
        close_session(session)


@pytest.mark.parametrize("patch", [
    {"enabled": "yes"}, {"request_attempts": 0}, {"name": "renamed"},
    {"adapter_type": "remotive"}, {"settings": []}, {"settings": {"unknown": "x"}},
    {"min_interval_seconds": True}, {"min_interval_seconds": -1},
])
def test_invalid_updates_are_atomic(database, patch):
    _, repo = database
    repo.configure(fixture_config("example", "unchanged.json"))
    with pytest.raises(ValueError):
        repo.configure(patch, name="example")
    config = repo.get("example")
    assert config.enabled is True and config.settings == {"path": "unchanged.json"}


def test_instances_share_remotive_budget_and_preserve_state(database, monkeypatch):
    url, repo = database
    calls = []
    def fetch(request, timeout):
        calls.append(request.full_url)
        return BytesIO((ROOT / "data/remotive_sample.json").read_bytes())
    monkeypatch.setattr(remotive_collector, "urlopen", fetch)
    repo.configure({"name": "python-feed", "adapter_type": "remotive", "settings": {"search": "python developer"}})
    assert run_collector("python-feed", database_url=url).jobs_new == 2
    repo.configure({"enabled": False, "min_interval_seconds": 43200}, name="python-feed")
    state = repo.get("python-feed")
    assert state.request_attempts == 1 and state.last_success_at is not None
    assert (state.next_allowed_at - state.last_attempt_at).total_seconds() == 43200
    repo.configure({"name": "second-feed", "adapter_type": "remotive"})
    assert run_collector("second-feed", database_url=url).status == "skipped"
    assert len(calls) == 1 and "search=python+developer" in calls[0]
    with pytest.raises(ValueError):
        repo.configure({"min_interval_seconds": 1}, name="second-feed")


def test_failed_instance_does_not_block_others(database):
    url, repo = database
    repo.configure(fixture_config("a-missing", "does-not-exist.json"))
    repo.configure(fixture_config("b-working", ROOT / "data/jobs_fixture.json"))
    results, errors = run_enabled(database_url=url)
    assert list(errors) == ["a-missing"] and results[0].source == "b-working"
    session = get_session(url)
    try:
        assert session.query(ProcessingRun).filter_by(source="a-missing").one().status == "failed"
    finally:
        close_session(session)


def test_management_cli(database, tmp_path, capsys):
    url, _ = database
    payload = tmp_path / "config.json"
    payload.write_text(json.dumps(fixture_config("sample", ROOT / "data/jobs_fixture.json")))
    prefix = ["--database-url", url]
    assert main(prefix + ["create", "--input", str(payload)]) == 0
    assert main(prefix + ["run", "--all"]) == 0
    assert main(prefix + ["list"]) == 0
    assert '"adapter_type": "json_fixture"' in capsys.readouterr().out
    payload.write_text('{"enabled": false}')
    assert main(prefix + ["update", "--name", "sample", "--input", str(payload)]) == 0
    assert main(prefix + ["run", "--name", "sample"]) == 0
    assert "disabled" in capsys.readouterr().out


def test_migration_preserves_policy_and_request_history(tmp_path):
    from alembic import command
    from alembic.config import Config
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url_override"] = url
    command.upgrade(config, "20260914_09")
    session = get_session(url)
    try:
        session.connection().exec_driver_sql(
            "INSERT INTO job_sources (name,endpoint,collection_strategy,response_retention,min_interval_seconds,request_attempts,last_http_status,next_allowed_at) "
            "VALUES ('remotive','https://remotive.com/api/remote-jobs','full_feed','none',21600,4,429,'2026-09-16 00:00:00')"
        )
        session.commit()
        before = session.connection().exec_driver_sql("SELECT * FROM job_sources").all()
    finally:
        close_session(session)
    command.upgrade(config, "head")
    row = SourceRepository(url).get("remotive")
    assert row.adapter_type == "remotive" and row.enabled and row.settings == {}
    assert row.request_attempts == 4 and row.last_http_status == 429
    command.downgrade(config, "20260914_09")
    session = get_session(url)
    try:
        assert session.connection().exec_driver_sql("SELECT * FROM job_sources").all() == before
    finally:
        close_session(session)


def test_shared_budget_rotates_instances(database, monkeypatch):
    from datetime import datetime, timedelta
    from jobsearch.storage import source_repository
    url, repo = database
    now = datetime(2026, 9, 15, 12)
    monkeypatch.setattr(source_repository, "utcnow", lambda: now)
    monkeypatch.setattr(remotive_collector, "urlopen", lambda *a, **k: BytesIO(b'{"jobs":[]}'))
    for name in ("a", "b"):
        repo.configure({"name": name, "adapter_type": "remotive"})
    first, errors = run_enabled(database_url=url)
    assert not errors and [(r.source, r.status) for r in first] == [("a", "completed"), ("b", "skipped")]
    now += timedelta(hours=6)
    second, errors = run_enabled(database_url=url)
    assert not errors and [(r.source, r.status) for r in second] == [("b", "completed"), ("a", "skipped")]
