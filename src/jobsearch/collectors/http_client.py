"""Shared bounded HTTP fetch, backoff recording, and opt-in response snapshots."""
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from pathlib import Path
from typing import Any
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request

from jobsearch.collectors.source import SourceSkipped
from jobsearch.models import JobSource
from jobsearch.storage.source_repository import SourceRepository


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


def fetch_records(*, source: JobSource, state: SourceRepository, endpoint: str,
                  decode: Callable[[bytes], list[Any]], opener: Callable[..., Any],
                  now: Callable[[], datetime], max_bytes: int, timeout: int = 30,
                  snapshot_path: Path | None = None) -> list[Any]:
    request = Request(endpoint, headers={"Accept": "application/json", "User-Agent": "JobSearchAutomation/0.1"})
    status = None
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read(max_bytes + 1)
    except HTTPError as exc:
        next_allowed = state.finish(source.name, http_status=exc.code, success=exc.code == 304,
            retry_at=retry_after(exc.headers.get("Retry-After") if exc.headers else None, now))
        if exc.code == 304:
            raise SourceSkipped("Server returned Not Modified", next_allowed, status="not_modified") from exc
        raise RuntimeError(f"{source.name} HTTP {exc.code}; request interval/backoff recorded; no retry attempted.") from exc
    except (URLError, TimeoutError) as exc:
        state.finish(source.name, http_status=None, success=False)
        raise RuntimeError(f"{source.name} request failed or timed out; request interval recorded; no retry attempted.") from exc
    try:
        records = decode(raw)
    except ValueError:
        state.finish(source.name, http_status=status, success=False)
        raise
    state.finish(source.name, http_status=status, success=True)
    if snapshot_path is not None:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with snapshot_path.open("xb") as handle:
            handle.write(raw)
    return records
