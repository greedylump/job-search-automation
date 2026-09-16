"""Bounded page collection; checkpoints become durable only with ingested jobs."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from jobsearch.collectors.source import SourceSkipped


class Page(list):
    """A decoded page. The shared HTTP client still counts its records normally."""
    def __init__(self, records, *, next_cursor=None):
        super().__init__(records)
        self.next_cursor = next_cursor


@dataclass
class CollectionBatch:
    records: list[Any]
    complete: bool
    next_cursor: str | int | None = None
    reason: str | None = None
    next_eligible_at: datetime | None = None
    pages: int = 0


class PaginatedAdapter:
    """Optional adapter mixin: implement build_page_request and decode_page.

    Subclasses also supply the normal validate/normalize/defaults contract.
    Cursor safety is an explicit provider-specific decision, never inferred.
    """
    collection_mode = "live"
    max_pages = 5
    max_records = 10000
    resume_safe = False
    max_response_bytes = 20 * 1024 * 1024

    def collect(self, config, database_url):
        from jobsearch.collectors import http_client
        from jobsearch.storage.source_repository import SourceRepository, utcnow
        state = SourceRepository(database_url)

        def fetch(position):
            return http_client.fetch_records(source=config.name, state=state,
                build_request=lambda current: self.build_page_request(current, position),
                decode=self.decode_page, opener=http_client.urlopen, now=utcnow,
                max_bytes=self.max_response_bytes)

        return collect_pages(fetch, cursor=(config.continuation or {}).get("cursor"),
                             max_pages=self.max_pages, max_records=self.max_records,
                             resume_safe=self.resume_safe)


def collect_pages(fetch_page: Callable[[Any], Page], *, cursor=None,
                  max_pages: int = 5, max_records: int = 10000,
                  resume_safe: bool = False) -> CollectionBatch:
    """fetch_page must use the shared HTTP client, with one request per page.

    Resume only when the provider guarantees a stable continuation. Otherwise
    restart from page one next run; already committed jobs deduplicate normally.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100")
    if type(max_records) is not int or not 1 <= max_records <= 100000:
        raise ValueError("max_records must be between 1 and 100000")
    position = cursor if resume_safe else None
    records, visited = [], set()
    pages = 0
    for _ in range(max_pages):
        try:
            page = fetch_page(position)
        except SourceSkipped as exc:
            # A 304 for one page cannot certify an entire multi-page refresh.
            return CollectionBatch(records, False, position if resume_safe else None,
                                   str(exc), exc.next_allowed_at, pages)
        except Exception:
            if not pages:
                raise
            return CollectionBatch(records, False, position if resume_safe else None,
                                   "Page request failed; continuation deferred", pages=pages)
        if not isinstance(page, Page):
            raise ValueError("Paginated decoder must return Page")
        next_cursor = page.next_cursor
        if next_cursor is not None and (type(next_cursor) not in (str, int) or len(str(next_cursor)) > 4096):
            raise ValueError("Invalid continuation cursor")
        if len(records) + len(page) > max_records:
            return CollectionBatch(records, False, position if resume_safe else None,
                                   "Record cap reached before ingesting this page", pages=pages)
        records.extend(page)
        pages += 1
        if next_cursor is None:
            return CollectionBatch(records, True, pages=pages)
        if str(next_cursor) in visited or next_cursor == position:
            return CollectionBatch(records, False, None, "Repeated cursor; restart required", pages=pages)
        visited.add(str(next_cursor))
        position = next_cursor
    return CollectionBatch(records, False, position if resume_safe else None,
                           "Page cap reached", pages=pages)
