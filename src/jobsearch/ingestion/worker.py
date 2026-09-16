"""Opt-in serial worker. No HTTP request occurs merely by importing this module."""
from datetime import datetime

from sqlalchemy import select

from jobsearch.collectors.adapters import adapter_for
from jobsearch.ingestion.runner import run_collector
from jobsearch.models import JobSource, RequestBudget
from jobsearch.storage.budget_repository import eligible_at
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage import source_repository
from jobsearch.storage.collection_control import control


def due_collectors(database_url, *, limit=20):
    if control(database_url)['paused']:
        return []
    session = get_session(database_url)
    try:
        now = source_repository.utcnow()
        configs = list(session.scalars(select(JobSource).where(JobSource.enabled.is_(True))))
        configs.sort(key=lambda c: (c.last_attempt_at or datetime.min, c.name))
        names = []
        for config in configs:
            if adapter_for(config).collection_mode != 'live':
                continue
            if config.lease_expires_at and config.lease_expires_at > now:
                continue
            if config.next_due_at and config.next_due_at > now:
                continue
            budget = session.get(RequestBudget, config.budget_name) if config.budget_name else None
            if budget is None:
                continue
            deadline = eligible_at(session, budget, now)
            if deadline is None or deadline <= now:
                names.append(config.name)
            if len(names) >= limit:
                break
        return names
    finally:
        close_session(session)


def run_due(database_url, *, limit=20, stopped=lambda: False):
    results, errors = [], {}
    # Recheck eligibility after each run: another board may consume shared quota.
    for name in due_collectors(database_url, limit=limit):
        if stopped():
            break
        if name not in due_collectors(database_url, limit=100000):
            continue
        try:
            results.append(run_collector(name, database_url=database_url))
        except Exception as exc:
            errors[name] = str(exc)
    return results, errors
