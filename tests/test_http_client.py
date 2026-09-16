from datetime import datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from jobsearch.collectors.http_client import fetch_records, _NoRedirects
from jobsearch.collectors.http_request import RequestSpec
from jobsearch.collectors.run_context import processing_run_id
from jobsearch.collectors.source import REMOTIVE, SourceSkipped
from jobsearch.models import RequestAttempt
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage import source_repository
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.repositories import ProcessingRunRepository
from jobsearch.storage.source_repository import SourceRepository


def test_each_request_reserves_and_records_sanitized_page_metadata(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'client.db'}"
    run_migrations(url)
    now = datetime(2026, 9, 15, 12)
    monkeypatch.setattr(source_repository, 'utcnow', lambda: now)
    session = get_session(url)
    try:
        run = ProcessingRunRepository(session).create(source='remotive')
        session.commit()
        run_id = run.id
    finally:
        close_session(session)
    calls = []
    def opener(request, timeout):
        session = get_session(url)
        try:
            row = session.query(RequestAttempt).order_by(RequestAttempt.id.desc()).first()
            assert row.completed_at is None and row.processing_run_id == run_id
        finally:
            close_session(session)
        calls.append(request.full_url)
        return BytesIO(b'[]')
    page = 1
    args = dict(source=REMOTIVE, state=SourceRepository(url),
        build_request=lambda config: RequestSpec(config.endpoint + f'?page={page}&api_key=SECRET&cursor=PRIVATE',
                                                headers={'Authorization': 'SECRET'}),
        decode=lambda raw: [], opener=opener, now=lambda: now, max_bytes=100)
    token = processing_run_id.set(run_id)
    try:
        fetch_records(**args)
        page = 2
        with pytest.raises(SourceSkipped):
            fetch_records(**args)
        assert len(calls) == 1
        now += timedelta(hours=6)
        fetch_records(**args)
    finally:
        processing_run_id.reset(token)
    session = get_session(url)
    try:
        rows = session.query(RequestAttempt).order_by(RequestAttempt.id).all()
        assert len(rows) == 2
        assert [r.request_metadata['page'] for r in rows] == [1, 2]
        assert all(r.processing_run_id == run_id and r.records_returned == 0 and r.response_bytes == 2 for r in rows)
        assert all(r.endpoint == REMOTIVE.endpoint and r.request_method == 'GET' for r in rows)
        assert all('SECRET' not in str(r.request_metadata) and 'PRIVATE' not in str(r.request_metadata) for r in rows)
    finally:
        close_session(session)


@pytest.mark.parametrize('failure', ['network', 'redirect', 'size'])
def test_client_error_is_recorded_without_secret(tmp_path, failure):
    url = f"sqlite:///{tmp_path / 'error.db'}"
    run_migrations(url)
    def opener(*a, **k):
        if failure == 'network':
            raise URLError('SECRET')
        if failure == 'redirect':
            raise HTTPError('https://example.com?token=SECRET', 302, 'SECRET', {}, None)
        return BytesIO(b'oversized')
    with pytest.raises((RuntimeError, ValueError)) as error:
        fetch_records(source=REMOTIVE, state=SourceRepository(url),
            build_request=lambda c: RequestSpec(c.endpoint), decode=lambda raw: [],
            opener=opener, now=datetime.utcnow, max_bytes=2)
    assert 'SECRET' not in str(error.value)
    assert error.value.__suppress_context__ or failure == 'size'
    session = get_session(url)
    try:
        row = session.query(RequestAttempt).one()
        assert row.outcome == {'network':'network_error', 'redirect':'http_error', 'size':'invalid_response'}[failure]
    finally:
        close_session(session)


def test_redirect_handler_never_follows():
    assert _NoRedirects().redirect_request(None, None, 302, '', {}, 'https://example.com') is None


def test_invalid_request_does_not_consume_budget(tmp_path):
    url = f"sqlite:///{tmp_path / 'invalid.db'}"
    run_migrations(url)
    with pytest.raises(ValueError):
        fetch_records(source=REMOTIVE, state=SourceRepository(url),
            build_request=lambda c: RequestSpec('http://example.com'), decode=lambda raw: [],
            opener=lambda *a, **k: pytest.fail('Must not send invalid request'), now=datetime.utcnow, max_bytes=100)
    session = get_session(url)
    try:
        assert session.query(RequestAttempt).count() == 0
    finally:
        close_session(session)
