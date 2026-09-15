from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from jobsearch.collectors import remotive_collector
from jobsearch.collectors.source import REMOTIVE
from jobsearch.models import RequestAttempt, ProcessingRun
from jobsearch.scripts.init_db import run_migrations
from jobsearch.scripts.run_remotive_ingestion import run_remotive_ingestion
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.source_repository import SourceRepository


@pytest.mark.parametrize("kind,expected,status", [
    ("success", "success", 200), ("invalid", "invalid_response", 200),
    ("limited", "http_error", 429), ("network", "network_error", None),
    ("unchanged", "not_modified", 304),
])
def test_attempt_saved_before_http_and_linked_to_run(tmp_path, monkeypatch, kind, expected, status):
    url = f"sqlite:///{tmp_path / 'ledger.db'}"

    def fetch(*args, **kwargs):
        session = get_session(url)
        try:
            attempt = session.query(RequestAttempt).one()
            assert attempt.outcome == "reserved" and attempt.completed_at is None
            assert session.get(ProcessingRun, attempt.processing_run_id).status == "running"
        finally:
            close_session(session)
        if kind in {"limited", "unchanged"}:
            raise HTTPError(REMOTIVE.endpoint, status, "response", {"Retry-After": "43200"}, None)
        if kind == "network":
            raise URLError("offline")
        return BytesIO(b'bad json' if kind == "invalid" else b'{"jobs":[]}')

    monkeypatch.setattr(remotive_collector, "urlopen", fetch)
    if kind in {"invalid", "limited", "network"}:
        with pytest.raises((ValueError, RuntimeError)):
            run_remotive_ingestion(database_url=url)
    else:
        run_remotive_ingestion(database_url=url)
    assert run_remotive_ingestion(database_url=url).status == "skipped"
    replay = tmp_path / "replay.json"
    replay.write_text('{"jobs":[]}')
    run_remotive_ingestion(database_url=url, replay_path=replay)
    session = get_session(url)
    try:
        attempt = session.query(RequestAttempt).one()
        assert attempt.outcome == expected and attempt.http_status == status
        assert attempt.completed_at is not None
        run = session.get(ProcessingRun, attempt.processing_run_id)
        assert run.collection_mode == "live"
        assert run.status == ("failed" if kind in {"invalid", "limited", "network"} else
                              "not_modified" if kind == "unchanged" else "completed")
        if kind == "limited":
            assert attempt.retry_at is not None
            assert attempt.next_allowed_at == attempt.retry_at
    finally:
        close_session(session)


def test_unfinished_reservation_survives_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'interrupted.db'}"
    run_migrations(url)
    source = SourceRepository(url).reserve(REMOTIVE)
    session = get_session(url)
    try:
        attempt = session.get(RequestAttempt, source.request_attempt_id)
        assert attempt.outcome == "reserved" and attempt.completed_at is None
        assert session.get(ProcessingRun, attempt.processing_run_id).collection_mode == "request"
    finally:
        close_session(session)
    assert SourceRepository(url).get("remotive").request_attempts == 1
