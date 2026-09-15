from datetime import datetime, timedelta, timezone

import re
from sqlalchemy import select, text

from jobsearch.collectors.source import SourceDefinition, SourceSkipped
from jobsearch.models.job_source import JobSource
from jobsearch.storage.database import get_session, close_session


def utcnow() -> datetime:
    """Naive UTC for consistent SQLite comparisons."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SourceRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def get(self, name: str) -> JobSource:
        session = get_session(self.database_url)
        try:
            config = session.get(JobSource, name)
            if config is None:
                raise ValueError(f"Collector {name!r} does not exist")
            return config
        finally:
            close_session(session)

    def list(self, *, enabled_only: bool = False) -> list[JobSource]:
        session = get_session(self.database_url)
        try:
            query = select(JobSource).order_by(JobSource.name)
            if enabled_only:
                query = query.where(JobSource.enabled.is_(True))
            return list(session.scalars(query))
        finally:
            close_session(session)

    def configure(self, payload: dict, *, name: str | None = None) -> JobSource:
        """Create or partially update validated configuration without resetting state."""
        from jobsearch.collectors.adapters import adapter_for, defaults_for
        allowed = {"endpoint", "enabled", "settings", "min_interval_seconds", "collection_strategy", "response_retention"}
        if not isinstance(payload, dict) or set(payload) - (allowed if name is not None else allowed | {"name", "adapter_type"}):
            raise ValueError("Unknown or protected collector configuration fields")
        session = get_session(self.database_url)
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            if name is None:
                name = payload.get("name")
                if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
                    raise ValueError("name must be a stable lowercase identifier (1-64 characters)")
                if session.get(JobSource, name) is not None:
                    raise ValueError(f"Collector {name!r} already exists")
                kind = payload.get("adapter_type")
                config = JobSource(name=name, adapter_type=kind, enabled=True,
                                   request_attempts=0, **defaults_for(kind))
                session.add(config)
            else:
                config = session.get(JobSource, name)
                if config is None:
                    raise ValueError(f"Collector {name!r} does not exist")
            for key, value in payload.items():
                setattr(config, key, value)
            adapter_for(config)
            if config.last_attempt_at is not None:
                eligible = config.last_attempt_at + timedelta(seconds=config.min_interval_seconds)
                if config.next_allowed_at is None or eligible > config.next_allowed_at:
                    config.next_allowed_at = eligible
            session.commit()
            return config
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)

    def reserve(self, definition: SourceDefinition | str) -> JobSource:
        """Commit the next request slot before HTTP; failed attempts also consume it."""
        session = get_session(self.database_url)
        try:
            # SQLite serializes the read/check/write even across separate processes.
            session.execute(text("BEGIN IMMEDIATE"))
            name = definition if isinstance(definition, str) else definition.name
            source = session.get(JobSource, name)
            if source is None:
                if isinstance(definition, str):
                    raise ValueError(f"Collector {name!r} does not exist")
                source = JobSource(**vars(definition), adapter_type="remotive", enabled=True, settings={}, request_attempts=0)
                session.add(source)
            from jobsearch.collectors.adapters import adapter_for
            adapter_for(source)
            if not source.enabled:
                raise SourceSkipped("Collector is disabled", source.next_allowed_at)
            now = utcnow()
            # All Remotive instances use the same public API budget, including
            # disabled instances and instances created after a previous request.
            members = list(session.scalars(select(JobSource).where(JobSource.adapter_type == source.adapter_type)))
            deadlines = [member.next_allowed_at for member in members if member.next_allowed_at is not None]
            if source.next_allowed_at is not None:
                deadlines.append(source.next_allowed_at)
            next_allowed = max(deadlines, default=None)
            if next_allowed is not None and now < next_allowed:
                raise SourceSkipped("Source request interval/backoff has not elapsed", next_allowed)
            source.last_attempt_at = now
            source.next_allowed_at = now + timedelta(seconds=source.min_interval_seconds)
            source.last_http_status = None
            source.request_attempts += 1
            session.commit()
            return source
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)

    def finish(self, name: str, *, http_status: int | None, success: bool,
               retry_at: datetime | None = None) -> datetime | None:
        session = get_session(self.database_url)
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            source = session.get(JobSource, name)
            source.last_http_status = http_status
            if success:
                source.last_success_at = utcnow()
            if retry_at is not None and (source.next_allowed_at is None or retry_at > source.next_allowed_at):
                source.next_allowed_at = retry_at
            session.commit()
            return source.next_allowed_at
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)
