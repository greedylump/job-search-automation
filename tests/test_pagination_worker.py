import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest

from jobsearch.collectors import adapters, http_client
from jobsearch.collectors.http_request import RequestSpec
from jobsearch.collectors.pagination import Page, PaginatedAdapter, collect_pages
from jobsearch.collectors.run_context import collector_lease
from jobsearch.collectors.source import SourceSkipped
from jobsearch.ingestion.runner import run_collector
from jobsearch.ingestion.worker import run_due
from jobsearch.models import Job, RequestAttempt
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage import source_repository
from jobsearch.storage.budget_repository import BudgetRepository
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.source_repository import SourceRepository


class TestAdapter(PaginatedAdapter):
    __test__ = False
    defaults = {'endpoint': 'https://example.test/jobs', 'collection_strategy': 'pages',
                'response_retention': 'none', 'min_interval_seconds': 0, 'settings': {}}
    max_pages = 1
    resume_safe = True

    def validate(self, config):
        pass

    def build_page_request(self, config, cursor):
        return RequestSpec(config.endpoint + f'?page={cursor or 1}')

    def decode_page(self, raw):
        data = json.loads(raw)
        return Page(data['jobs'], next_cursor=data['next'])

    def normalize(self, config, payload):
        return JsonJobNormalizer.normalize(payload)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'pages.db'}"
    run_migrations(url)
    clock = [datetime(2026, 9, 15, 12)]
    monkeypatch.setattr(source_repository, 'utcnow', lambda: clock[0])
    adapter = TestAdapter()
    monkeypatch.setitem(adapters.ADAPTERS, 'testpages', adapter)
    repo = SourceRepository(url)
    repo.configure({'name': 'board', 'adapter_type': 'testpages', 'refresh_interval_seconds': 43200})
    calls = []
    def fetch(request, timeout):
        page = int(parse_qs(urlsplit(request.full_url).query)['page'][0])
        calls.append(page)
        return BytesIO(json.dumps({'jobs': [{'id': str(page), 'title': 'Engineer'}],
                                   'next': 2 if page == 1 else None}).encode())
    monkeypatch.setattr(http_client, 'urlopen', fetch)
    return url, repo, clock, calls, adapter


def test_partial_checkpoint_and_resume_are_atomic(setup):
    url, repo, clock, calls, _ = setup
    first = run_collector('board', database_url=url)
    assert first.status == 'partial' and first.jobs_new == first.pages_collected == 1
    assert repo.get('board').continuation == {'cursor': 2}
    assert repo.get('board').last_complete_refresh_at is None
    assert run_due(url) == ([], {})
    clock[0] += timedelta(minutes=5)
    results, errors = run_due(url)
    assert not errors and results[0].status == 'completed' and results[0].jobs_new == 1
    assert calls == [1, 2]
    assert repo.get('board').continuation is None
    assert repo.get('board').next_due_at == clock[0] + timedelta(hours=12)
    assert run_due(url) == ([], {})


def test_budget_exhaustion_is_partial_not_complete(setup):
    url, repo, clock, calls, adapter = setup
    adapter.max_pages = 5
    BudgetRepository(url).configure('testpages', min_interval_seconds=0,
        windows=[{'window_seconds': 3600, 'max_requests': 1}])
    result = run_collector('board', database_url=url)
    assert result.status == 'partial' and calls == [1]
    assert result.next_eligible_at == clock[0] + timedelta(hours=1)
    assert repo.get('board').continuation == {'cursor': 2}
    clock[0] += timedelta(hours=1)
    assert run_collector('board', database_url=url).status == 'completed'


def test_ingestion_rollback_does_not_advance_cursor(setup, monkeypatch):
    url, repo, _, calls, adapter = setup
    def bad(*args):
        raise ValueError('bad normalization')
    monkeypatch.setattr(adapter, 'normalize', bad)
    with pytest.raises(ValueError):
        run_collector('board', database_url=url)
    assert repo.get('board').continuation is None and repo.get('board').lease_token is None
    session = get_session(url)
    try:
        assert session.query(Job).count() == 0
        assert session.query(RequestAttempt).one().outcome == 'success'
    finally:
        close_session(session)


def test_exclusive_claim_and_expired_owner_fencing(setup):
    url, repo, clock, _, _ = setup
    def claim(_):
        try:
            return repo.claim('board')
        except SourceSkipped:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(claim, range(2)))
    assert sum(t is not None for t in tokens) == 1
    old = next(t for t in tokens if t)
    clock[0] += timedelta(minutes=6)
    new = repo.claim('board')
    token = collector_lease.set(old)
    try:
        with pytest.raises(RuntimeError, match='lease'):
            repo.reserve('board')
    finally:
        collector_lease.reset(token)
    repo.release('board', old)
    assert repo.get('board').lease_token == new


def test_restart_policy_caps_and_repeated_cursor():
    seen = []
    def fetch(cursor):
        seen.append(cursor)
        return Page([1], next_cursor='next')
    batch = collect_pages(fetch, cursor='old', max_pages=2, resume_safe=False)
    assert seen == [None, 'next'] and not batch.complete and batch.next_cursor is None
    assert 'Repeated' in batch.reason
    capped = collect_pages(lambda _: Page([1, 2], next_cursor=2), max_records=1)
    assert capped.records == [] and not capped.complete


def test_worker_ignores_disabled_and_fixture_instances(setup):
    url, repo, _, calls, _ = setup
    repo.configure({'enabled': False}, name='board')
    repo.configure({'name': 'fixture', 'adapter_type': 'json_fixture', 'settings': {'path': 'missing.json'}})
    assert run_due(url) == ([], {}) and calls == []


def test_page_failure_preserves_prior_pages(setup, monkeypatch):
    from urllib.error import URLError
    url, repo, _, calls, adapter = setup
    adapter.max_pages = 5
    first = http_client.urlopen
    def fetch(request, timeout):
        if 'page=2' in request.full_url:
            raise URLError('offline')
        return first(request, timeout=timeout)
    monkeypatch.setattr(http_client, 'urlopen', fetch)
    result = run_collector('board', database_url=url)
    assert result.status == 'partial' and result.jobs_new == 1
    assert repo.get('board').continuation == {'cursor': 2}
    session = get_session(url)
    try:
        assert [a.outcome for a in session.query(RequestAttempt).order_by(RequestAttempt.id)] == ['success', 'network_error']
    finally:
        close_session(session)


def test_worker_cli_once_and_loop_stop(setup, monkeypatch):
    from jobsearch.scripts import collection_worker
    url, _, _, calls, _ = setup
    assert collection_worker.main(['--database-url', url, '--once']) == 0
    assert calls == [1]
    class Stop:
        stopped = False
        def is_set(self): return self.stopped
        def set(self): self.stopped = True
        def wait(self, seconds):
            assert seconds == 60
            self.stopped = True
    monkeypatch.setattr(collection_worker, 'Event', Stop)
    assert collection_worker.main(['--database-url', url, '--loop']) == 0
    assert calls == [1]  # Deferred collector is not polled again.
