from collections.abc import Callable
from typing import Any
from datetime import datetime

from jobsearch.collectors.adapters import adapter_for
from jobsearch.collectors.source import SourceSkipped
from jobsearch.config.settings import get_settings
from jobsearch.ingestion.pipeline import run_ingestion
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.source_repository import SourceRepository


def run_collector(name: str, *, database_url: str | None = None,
                  collect_override: Callable[[], list[Any]] | None = None,
                  collection_mode: str | None = None):
    url = database_url or get_settings().database_url
    run_migrations(url)
    repository = SourceRepository(url)
    config = repository.get(name)
    adapter = adapter_for(config)

    def collect():
        current = repository.get(name)
        if not current.enabled:
            raise SourceSkipped("Collector is disabled", current.next_allowed_at)
        adapter_for(current)
        return collect_override() if collect_override is not None else adapter.collect(current, url)

    def normalize(payload):
        job = adapter.normalize(config, payload)
        job.source = config.name
        return job

    return run_ingestion(source=config.name, collect=collect, normalize=normalize,
                         database_url=url, collection_mode=collection_mode or adapter.collection_mode)


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
