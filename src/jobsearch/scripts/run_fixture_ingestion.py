from __future__ import annotations

from pathlib import Path

from jobsearch.collectors.json_fixture_collector import JsonFixtureCollector
from jobsearch.config.settings import get_settings
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.source_repository import SourceRepository
from jobsearch.ingestion.runner import run_collector


def run_fixture_ingestion(fixture_path: str | Path = "data/jobs_fixture.json") -> int:
    """Ingest a fixture through the same pipeline used for live sources."""
    url = get_settings().database_url
    run_migrations(url)
    repo = SourceRepository(url)
    settings = {"path": str(fixture_path)}
    if any(config.name == "fixture_json" for config in repo.list()):
        repo.configure({"settings": settings}, name="fixture_json")
    else:
        repo.configure({"name": "fixture_json", "adapter_type": "json_fixture", "settings": settings})
    run = run_collector("fixture_json", database_url=url)
    return run.jobs_new


if __name__ == "__main__":
    run_fixture_ingestion()
