import json
from datetime import datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from jobsearch.collectors import http_client, usajobs_collector as usa
from jobsearch.ingestion.runner import run_collector
from jobsearch.models import Job, RequestAttempt
from jobsearch.normalization.usajobs_normalizer import normalize
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage import source_repository
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.source_repository import SourceRepository


def item(identifier='123'):
    return {'MatchedObjectId': identifier, 'MatchedObjectDescriptor': {
        'PositionTitle': 'IT Specialist', 'OrganizationName': 'Example Agency',
        'PositionLocationDisplay': 'Chicago, Illinois',
        'PositionURI': 'https://www.usajobs.gov/job/' + identifier,
        'ApplyURI': ['https://www.usajobs.gov/job/' + identifier + '?PostingChannelID=RESTAPI'],
        'PositionRemuneration': [{'MinimumRange': '75000', 'MaximumRange': '95000', 'RateIntervalCode': 'PA'}],
        'PublicationStartDate': '2026-09-17T00:00:00Z',
        'UserArea': {'Details': {'JobSummary': '<p>Example summary</p>', 'TeleworkEligible': True}}}}


def response(items, total):
    return json.dumps({'SearchResult': {'SearchResultCount': len(items),
        'SearchResultCountAll': total, 'SearchResultItems': items}}).encode()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBSEARCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBSEARCH_USAJOBS_API_KEY', 'TEST_SECRET')
    monkeypatch.setenv('JOBSEARCH_USAJOBS_EMAIL', 'private@example.test')
    url = f'sqlite:///{tmp_path / "usa.db"}'
    run_migrations(url)
    repo = SourceRepository(url)
    repo.configure({'name': 'usajobs', 'adapter_type': 'usajobs', 'refresh_interval_seconds': 21600,
                    'settings': {'page_size': 1, 'max_pages': 3, 'query': {'JobCategoryCode': '2210'}}})
    clock = [datetime(2026, 9, 17, 12)]
    monkeypatch.setattr(source_repository, 'utcnow', lambda: clock[0])
    monkeypatch.setattr(usa, 'utcnow', lambda: clock[0])
    monkeypatch.setattr(usa.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + timedelta(seconds=seconds)))
    monkeypatch.setattr(http_client, 'urlopen', lambda *a, **kw: pytest.fail('Unexpected live HTTP'))
    return url, repo, clock


def test_pagination_credentials_and_dedup(setup, monkeypatch):
    url, repo, clock = setup
    calls = []
    def fetch(request, timeout):
        page = int(parse_qs(urlsplit(request.full_url).query)['Page'][0])
        headers = {k.lower(): v for k, v in request.header_items()}
        assert headers['authorization-key'] == 'TEST_SECRET'
        assert headers['user-agent'] == 'private@example.test'
        assert 'TEST_SECRET' not in request.full_url
        calls.append(page)
        return BytesIO(response([item(str(page))], 2))
    monkeypatch.setattr(http_client, 'urlopen', fetch)
    run = run_collector('usajobs', database_url=url)
    assert (run.status, run.jobs_new, run.pages_collected) == ('completed', 2, 2)
    session = get_session(url)
    try:
        attempts = session.query(RequestAttempt).all()
        assert [a.request_metadata['page'] for a in attempts] == [1, 2]
        assert all(a.processing_run_id == run.id and a.outcome == 'success' for a in attempts)
        assert all('TEST_SECRET' not in str(a.__dict__) and 'private@example.test' not in str(a.__dict__) for a in attempts)
    finally:
        close_session(session)
    assert run_collector('usajobs', database_url=url).status == 'skipped'
    clock[0] += timedelta(hours=7)
    assert run_collector('usajobs', database_url=url).jobs_deduplicated == 2
    assert calls == [1, 2, 1, 2]


def test_page_cap_is_partial_and_does_not_claim_full_refresh(setup, monkeypatch):
    url, repo, clock = setup
    repo.configure({'settings': {'page_size': 1, 'max_pages': 1}}, name='usajobs')
    monkeypatch.setattr(http_client, 'urlopen', lambda *a, **kw: BytesIO(response([item()], 10)))
    run = run_collector('usajobs', database_url=url)
    assert run.status == 'partial' and run.jobs_new == 1
    config = repo.get('usajobs')
    assert config.last_complete_refresh_at is None and config.continuation is None
    assert config.next_due_at >= clock[0] + timedelta(hours=6)


def test_429_records_retry_without_retrying_or_exposing_headers(setup, monkeypatch, caplog):
    url, repo, _ = setup
    def fail(*args, **kwargs):
        raise HTTPError(usa.API_URL, 429, 'TEST_SECRET', {'Retry-After': '3600'}, None)
    monkeypatch.setattr(http_client, 'urlopen', fail)
    with pytest.raises(RuntimeError, match='HTTP 429'):
        run_collector('usajobs', database_url=url)
    assert 'TEST_SECRET' not in caplog.text
    session = get_session(url)
    try:
        row = session.query(RequestAttempt).one()
        assert row.http_status == 429 and row.retry_at is not None
        assert session.query(Job).count() == 0
    finally:
        close_session(session)


def test_missing_credentials_no_attempt(setup, monkeypatch):
    url, _, _ = setup
    monkeypatch.setenv('JOBSEARCH_USAJOBS_API_KEY', '')
    with pytest.raises(ValueError, match='requires valid'):
        run_collector('usajobs', database_url=url)
    session = get_session(url)
    try:
        assert session.query(RequestAttempt).count() == 0
    finally:
        close_session(session)


@pytest.mark.parametrize('settings', [
    {'api_key': 'no'}, {'query': {'Authorization-Key': 'no'}}, {'page_size': 501},
    {'max_pages': True}, {'query': {'DatePosted': '61'}}, {'query': {'RemoteIndicator': 'maybe'}}])
def test_rejects_unsafe_or_invalid_settings(setup, settings):
    _, repo, _ = setup
    with pytest.raises(ValueError):
        repo.configure({'settings': settings}, name='usajobs')


def test_normalization_preserves_units_links_and_unknown_remote():
    job = normalize(item())
    assert job.source_job_id == '123' and job.salary_min == 75000 and job.salary_period == 'annual'
    assert job.remote_type is None and 'PostingChannelID=RESTAPI' in job.apply_url
    assert '<p>' not in job.description and job.posted_at is not None
    assert normalize({'MatchedObjectId': True, 'MatchedObjectDescriptor': []}).source_job_id is None


@pytest.mark.parametrize('raw', [b'{}', b'not json', response([], 5)])
def test_invalid_envelopes_rejected(raw):
    with pytest.raises((ValueError, KeyError)):
        usa.USAJobsAdapter.decode(raw, 1, 100)
