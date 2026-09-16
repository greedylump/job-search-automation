from collections.abc import Callable
from typing import Any
from datetime import datetime

from jobsearch.collectors.adapters import adapter_for
from jobsearch.collectors.source import SourceSkipped
from jobsearch.config.settings import get_settings
from jobsearch.ingestion.pipeline import run_ingestion
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.source_repository import SourceRepository
from jobsearch.storage import source_repository
from jobsearch.collectors.run_context import collector_lease


def run_collector(name: str, *, database_url: str | None = None,
                  collect_override: Callable[[], list[Any]] | None = None,
                  collection_mode: str | None = None):
    url = database_url or get_settings().database_url
    run_migrations(url)
    repository = SourceRepository(url)
    config = repository.get(name)
    adapter = adapter_for(config)
    lease = None
    lease_context = None

    def collect():
        nonlocal lease, lease_context, config, adapter
        current = repository.get(name)
        if not current.enabled:
            raise SourceSkipped("Collector is disabled", current.next_allowed_at)
        if collection_mode != "replay" and current.next_due_at and source_repository.utcnow() < current.next_due_at:
            raise SourceSkipped("Collector refresh is not due", current.next_due_at)
        adapter_for(current)
        lease = repository.claim(name, replay=collection_mode == "replay")
        lease_context = collector_lease.set(lease)
        current = repository.get(name)
        config = current
        adapter = adapter_for(current)
        return collect_override() if collect_override is not None else adapter.collect(current, url)

    def normalize(payload):
        job = adapter.normalize(config, payload)
        job.source = config.name
        return job

    failed = False
    try:
        return run_ingestion(source=config.name, collect=collect, normalize=normalize,
                             database_url=url, collection_mode=collection_mode or adapter.collection_mode)
    except Exception:
        failed = True
        raise
    finally:
        if lease_context is not None:
            collector_lease.reset(lease_context)
        if lease is not None:
            repository.release(name, lease, failed=failed)


def run_enabled(*, database_url: str | None = None):
    """Run each enabled row once; a failed instance does not block the others."""
    url = database_url or get_settings().database_url
    run_migrations(url)
    results, errors = [], {}
    configs = SourceRepository(url).list(enabled_only=True)
    # Avoid starving instances sharing a budget: never/least recently attempted first.
    configs.sort(key=lambda config: (config.last_attempt_at or datetime.min, config.name))
    for config in configs:
        try:
            results.append(run_collector(config.name, database_url=url))
        except Exception as exc:
            errors[config.name] = str(exc)
    return results, errors
