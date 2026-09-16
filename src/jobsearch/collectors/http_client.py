"""Shared bounded HTTP fetch, backoff recording, and opt-in response snapshots."""
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from pathlib import Path
from typing import Any
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from http.client import HTTPException

from jobsearch.collectors.source import SourceSkipped, SourceDefinition
from jobsearch.collectors.http_request import RequestSpec
from jobsearch.models import JobSource
from jobsearch.storage.source_repository import SourceRepository
from jobsearch.storage.collection_control import ensure_collection_allowed


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect would be an additional, unreserved network request.
        return None


def urlopen(request, *, timeout):
    return build_opener(_NoRedirects()).open(request, timeout=timeout)


def retry_after(value: str | None, now: Callable[[], datetime]) -> datetime | None:
    if not value:
        return None
    try:
        if value.strip().isdigit():
            return now() + timedelta(seconds=int(value.strip()))
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_records(*, source: str | SourceDefinition, state: SourceRepository,
                  build_request: Callable[[JobSource], RequestSpec],
                  decode: Callable[[bytes], list[Any]], opener: Callable[..., Any],
                  now: Callable[[], datetime], max_bytes: int, timeout: int = 30,
                  snapshot_path: Path | None = None) -> list[Any]:
    if max_bytes <= 0 or timeout <= 0:
        raise ValueError("Response size and timeout must be positive")
    if snapshot_path is not None and snapshot_path.exists():
        raise FileExistsError(f"Snapshot already exists: {snapshot_path}")
    report = ensure_collection_allowed(state.database_url)
    if snapshot_path is not None and not any(snapshot_path.resolve().is_relative_to(Path(root)) for root in report['storage_dirs']):
        raise ValueError('Snapshot destination must be inside a tracked storage directory; configure JOBSEARCH_STORAGE_DIRS')
    request = None

    def describe(config):
        nonlocal request
        spec = build_request(config)
        metadata = spec.metadata()
        request = Request(spec.url, headers={"Accept": "application/json",
                          "User-Agent": "JobSearchAutomation/0.1", **spec.headers}, method="GET")
        return metadata

    # Request construction uses current configuration inside the same transaction
    # as permission checking, budget consumption and attempt insertion.
    ensure_collection_allowed(state.database_url)
    source = state.reserve(source, describe=describe)
    status = None
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read(max_bytes + 1)
    except HTTPError as exc:
        next_allowed = state.finish(source.name, http_status=exc.code, success=exc.code == 304,
            attempt_id=source.request_attempt_id, outcome="not_modified" if exc.code == 304 else "http_error",
            retry_at=retry_after(exc.headers.get("Retry-After") if exc.headers else None, now))
        if exc.code == 304:
            raise SourceSkipped("Server returned Not Modified", next_allowed, status="not_modified") from None
        raise RuntimeError(f"{source.name} HTTP {exc.code}; request interval/backoff recorded; no retry attempted.") from None
    except (URLError, OSError, HTTPException):
        state.finish(source.name, http_status=status, success=False,
                     attempt_id=source.request_attempt_id, outcome="network_error")
        raise RuntimeError(f"{source.name} request failed or timed out; request interval recorded; no retry attempted.") from None
    try:
        if len(raw) > max_bytes:
            raise ValueError("Response exceeds configured byte limit")
        records = decode(raw)
        if not isinstance(records, list):
            raise ValueError("Decoder must return a list")
    except Exception:
        state.finish(source.name, http_status=status, success=False,
                     attempt_id=source.request_attempt_id, outcome="invalid_response", response_bytes=len(raw))
        raise ValueError("Response could not be decoded as a record list or exceeds configured byte limit") from None
    state.finish(source.name, http_status=status, success=True,
                 attempt_id=source.request_attempt_id, outcome="success",
                 response_bytes=len(raw), records_returned=len(records))
    if snapshot_path is not None:
        ensure_collection_allowed(state.database_url)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with snapshot_path.open("xb") as handle:
            handle.write(raw)
    return records
