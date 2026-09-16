from datetime import datetime, timedelta, timezone

import re
from uuid import uuid4
from sqlalchemy import select, text

from jobsearch.collectors.source import SourceDefinition, SourceSkipped
from jobsearch.models.job_source import JobSource
from jobsearch.models import RequestAttempt, ProcessingRun, RequestBudget
from jobsearch.storage.budget_repository import eligible_at
from jobsearch.collectors.run_context import processing_run_id, collector_lease
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
        allowed = {"endpoint", "enabled", "settings", "min_interval_seconds", "refresh_interval_seconds", "collection_strategy", "response_retention"}
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
                                   request_attempts=0, refresh_interval_seconds=0, **defaults_for(kind))
                self._attach_budget(session, config)
                session.add(config)
            else:
                config = session.get(JobSource, name)
                if config is None:
                    raise ValueError(f"Collector {name!r} does not exist")
                if config.lease_expires_at and config.lease_expires_at > utcnow() and set(payload) - {"enabled"}:
                    raise ValueError("Cannot change configuration while a collector is running")
            if set(payload) & {"settings", "endpoint"}:
                config.continuation = None
            for key, value in payload.items():
                setattr(config, key, value)
            adapter_for(config)
            if type(config.refresh_interval_seconds) is not int or config.refresh_interval_seconds < 0:
                raise ValueError("refresh_interval_seconds must be a nonnegative integer")
            if config.last_complete_refresh_at:
                due = config.last_complete_refresh_at + timedelta(seconds=config.refresh_interval_seconds)
                config.next_due_at = max(config.next_due_at or due, due)
            if config.last_attempt_at is not None:
                eligible = config.last_attempt_at + timedelta(seconds=config.min_interval_seconds)
                if config.next_allowed_at is None or eligible > config.next_allowed_at:
                    config.next_allowed_at = eligible
            # Legacy setting remains a supported alias for shared request spacing.
            if config.budget_name and "min_interval_seconds" in payload:
                budget = session.get(RequestBudget, config.budget_name)
                budget.min_interval_seconds = max(budget.min_interval_seconds, config.min_interval_seconds)
                if config.next_allowed_at:
                    budget.next_allowed_at = max(budget.next_allowed_at or config.next_allowed_at, config.next_allowed_at)
            session.commit()
            return config
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)

    @staticmethod
    def _attach_budget(session, source):
        if source.adapter_type == "json_fixture":
            return
        # Adapter defaults select the budget; callers cannot bypass it by renaming a board.
        source.budget_name = source.adapter_type
        budget = session.get(RequestBudget, source.budget_name)
        if budget is None:
            budget = RequestBudget(name=source.budget_name, min_interval_seconds=source.min_interval_seconds)
            session.add(budget)
            session.flush()

    def claim(self, name, *, replay=False):
        session = get_session(self.database_url)
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            source = session.get(JobSource, name)
            now = utcnow()
            if not source.enabled:
                raise SourceSkipped("Collector is disabled", source.next_due_at)
            if source.lease_expires_at and source.lease_expires_at > now:
                raise SourceSkipped("Collector already running", source.lease_expires_at)
            if not replay and source.next_due_at and source.next_due_at > now:
                raise SourceSkipped("Collector refresh is not due", source.next_due_at)
            source.lease_token = uuid4().hex
            source.lease_expires_at = now + timedelta(minutes=5)
            session.commit()
            return source.lease_token
        finally:
            close_session(session)

    def release(self, name, token, *, failed=False):
        session = get_session(self.database_url)
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            source = session.get(JobSource, name)
            if source.lease_token == token:
                source.lease_token = None
                source.lease_expires_at = None
                if failed:
                    deadline = utcnow() + timedelta(minutes=5)
                    budget = session.get(RequestBudget, source.budget_name) if source.budget_name else None
                    if budget is not None:
                        deadline = max(deadline, eligible_at(session, budget, utcnow()) or deadline)
                    source.next_due_at = max(source.next_due_at or deadline, deadline)
                session.commit()
        finally:
            close_session(session)

    def reserve(self, definition: SourceDefinition | str, *, describe=None) -> JobSource:
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
                source = JobSource(**vars(definition), adapter_type="remotive", enabled=True, settings={}, request_attempts=0, refresh_interval_seconds=0)
                self._attach_budget(session, source)
                session.add(source)
            from jobsearch.collectors.adapters import adapter_for
            adapter_for(source)
            if not source.enabled:
                raise SourceSkipped("Collector is disabled", source.next_allowed_at)
            now = utcnow()
            token = collector_lease.get()
            if token is not None:
                if source.lease_token != token or not source.lease_expires_at or source.lease_expires_at <= now:
                    raise RuntimeError("Collector lease expired or was replaced")
                source.lease_expires_at = now + timedelta(minutes=5)
            elif source.lease_expires_at and source.lease_expires_at > now:
                raise SourceSkipped("Collector already running", source.lease_expires_at)
            budget = session.get(RequestBudget, source.budget_name)
            if budget is None:
                raise ValueError("HTTP collector requires a shared request budget")
            next_allowed = eligible_at(session, budget, now)
            if next_allowed is not None and now < next_allowed:
                raise SourceSkipped("Source request interval/backoff has not elapsed", next_allowed)
            descriptor = describe(source) if describe is not None else {}
            source.last_attempt_at = now
            budget.last_attempt_at = now
            budget.next_allowed_at = now + timedelta(seconds=budget.min_interval_seconds)
            source.next_allowed_at = budget.next_allowed_at
            source.last_http_status = None
            source.request_attempts += 1
            run_id = processing_run_id.get()
            if run_id is None:
                # Low-level callers still receive a durable parent run.
                from jobsearch.storage.repositories import ProcessingRunRepository
                run = ProcessingRunRepository(session).create(source=name, ai_cost=0.0)
                run.collection_mode = "request"
                run_id = run.id
            attempt = RequestAttempt(processing_run_id=run_id, source=name, budget_name=budget.name,
                endpoint=descriptor.pop("endpoint", source.endpoint), reserved_at=now, outcome="reserved",
                **descriptor,
                next_allowed_at=source.next_allowed_at)
            session.add(attempt)
            session.flush()
            source.request_attempt_id = attempt.id
            session.commit()
            return source
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)

    def finish(self, name: str, *, http_status: int | None, success: bool,
               retry_at: datetime | None = None, attempt_id: int | None = None,
               outcome: str | None = None, response_bytes: int | None = None,
               records_returned: int | None = None) -> datetime | None:
        session = get_session(self.database_url)
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            source = session.get(JobSource, name)
            budget = session.get(RequestBudget, source.budget_name)
            source.last_http_status = http_status
            if success:
                source.last_success_at = utcnow()
            if retry_at is not None and (source.next_allowed_at is None or retry_at > source.next_allowed_at):
                source.next_allowed_at = retry_at
            if budget is not None and retry_at is not None:
                budget.next_allowed_at = max(budget.next_allowed_at or retry_at, retry_at)
            if attempt_id is not None:
                attempt = session.get(RequestAttempt, attempt_id)
                if attempt is None or attempt.source != name or attempt.completed_at is not None:
                    raise ValueError("Unknown or already completed request attempt")
                attempt.completed_at = utcnow()
                attempt.http_status = http_status
                attempt.response_bytes = response_bytes
                attempt.records_returned = records_returned
                attempt.retry_at = retry_at
                attempt.next_allowed_at = source.next_allowed_at
                attempt.outcome = outcome or ("success" if success else "failed")
                run = session.get(ProcessingRun, attempt.processing_run_id)
                if run.collection_mode == "request":
                    run.status = "completed" if success else "failed"
                    run.completed_at = attempt.completed_at
            session.commit()
            return source.next_allowed_at
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)
