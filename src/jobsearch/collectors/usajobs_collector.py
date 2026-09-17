"""USAJOBS search with header-only credentials and bounded, tracked pagination."""
import json
import os
import time
from datetime import timedelta
from urllib.parse import urlencode

from jobsearch.collectors import http_client
from jobsearch.collectors.http_request import RequestSpec
from jobsearch.collectors.pagination import Page, collect_pages
from jobsearch.config.settings import get_settings
from jobsearch.storage.source_repository import SourceRepository, utcnow

API_URL = 'https://data.usajobs.gov/api/search'


def credentials():
    get_settings()  # Load .env without overriding the process environment.
    values = [os.getenv(name, '').strip() for name in
              ('JOBSEARCH_USAJOBS_API_KEY', 'JOBSEARCH_USAJOBS_EMAIL')]
    if any(not value or '\r' in value or '\n' in value for value in values):
        raise ValueError('USAJOBS requires valid JOBSEARCH_USAJOBS_API_KEY and JOBSEARCH_USAJOBS_EMAIL')
    return values


class USAJobsAdapter:
    collection_mode = 'live'
    defaults = dict(endpoint=API_URL, collection_strategy='pages', response_retention='none',
                    min_interval_seconds=2, settings={'query': {'JobCategoryCode': '2210'},
                                                     'page_size': 100, 'max_pages': 5})

    def validate(self, config):
        if config.endpoint != API_URL or config.collection_strategy != 'pages' or config.response_retention != 'none':
            raise ValueError('USAJOBS requires its fixed search endpoint, pages strategy, and no response retention')
        if config.min_interval_seconds < 2:
            raise ValueError('USAJOBS local policy requires at least two seconds between requests')
        if config.refresh_interval_seconds < 0:
            raise ValueError('Refresh interval must be nonnegative')
        settings = config.settings
        if set(settings) - {'query', 'page_size', 'max_pages'}:
            raise ValueError('Unknown USAJOBS setting; credentials belong only in environment variables')
        for key, maximum, default in [('page_size', 500, 100), ('max_pages', 20, 5)]:
            value = settings.get(key, default)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{key} must be between 1 and {maximum}')
        query = settings.get('query', {})
        allowed = {'Keyword', 'PositionTitle', 'JobCategoryCode', 'LocationName', 'Organization',
                   'DatePosted', 'RemoteIndicator', 'HiringPath'}
        if not isinstance(query, dict) or set(query) - allowed:
            raise ValueError('Unsupported USAJOBS search parameter')
        if any(not isinstance(v, str) or not v.strip() or len(v) > 500 or '\n' in v or '\r' in v for v in query.values()):
            raise ValueError('Search values must be nonblank strings of at most 500 characters')
        if 'DatePosted' in query and (not query['DatePosted'].isdigit() or not 0 <= int(query['DatePosted']) <= 60):
            raise ValueError('DatePosted must be 0 through 60')
        if 'RemoteIndicator' in query and query['RemoteIndicator'] not in {'True', 'False'}:
            raise ValueError('RemoteIndicator must be True or False')

    def build_request(self, config, page):
        key, email = credentials()
        query = dict(config.settings.get('query', {}), Page=page,
                     ResultsPerPage=config.settings.get('page_size', 100),
                     WhoMayApply='Public', Fields='Full', SortField='opendate', SortDirection='Desc')
        return RequestSpec(API_URL + '?' + urlencode(query), headers={
            'Host': 'data.usajobs.gov', 'User-Agent': email, 'Authorization-Key': key})

    @staticmethod
    def decode(raw, page, size):
        data = json.loads(raw)
        result = data['SearchResult']
        items = result['SearchResultItems']
        count, total = result['SearchResultCount'], result['SearchResultCountAll']
        if any(type(n) is not int or n < 0 for n in (count, total)):
            raise ValueError('Invalid USAJOBS result counts')
        if not isinstance(items, list) or len(items) != count or count > size or total < count:
            raise ValueError('Inconsistent USAJOBS result envelope')
        more = page * size < total
        if (page - 1) * size < total and not items:
            raise ValueError('Empty USAJOBS page before end of search')
        return Page(items, next_cursor=page + 1 if more else None)

    def collect(self, config, database_url):
        credentials()  # Fail before reserving any request if credentials are missing.
        state = SourceRepository(database_url)
        size = config.settings.get('page_size', 100)
        def fetch(cursor):
            page = cursor or 1
            if page > 1:
                time.sleep(2)  # Local pacing; the shared budget still authorizes every page.
            return http_client.fetch_records(source=config.name, state=state,
                build_request=lambda current: self.build_request(current, page),
                decode=lambda raw: self.decode(raw, page, size), opener=http_client.urlopen,
                now=utcnow, max_bytes=20 * 1024 * 1024)
        batch = collect_pages(fetch, max_pages=config.settings.get('max_pages', 5),
                              max_records=10000, resume_safe=False)
        # Page numbers are not stable snapshots. Restart and deduplicate next refresh;
        # do not repeatedly fetch page one every five minutes after a bounded sample.
        if not batch.complete:
            batch.next_eligible_at = max(batch.next_eligible_at or utcnow(),
                                         utcnow() + timedelta(seconds=max(21600, config.refresh_interval_seconds)))
        return batch

    def normalize(self, config, payload):
        from jobsearch.normalization.usajobs_normalizer import normalize
        return normalize(payload)
