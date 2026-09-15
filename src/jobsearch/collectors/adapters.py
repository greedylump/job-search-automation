"""Adapter contract and trusted implementation registry; instances live in SQL."""
from typing import Any, Protocol
from copy import deepcopy

from jobsearch.models import Job, JobSource


class CollectorAdapter(Protocol):
    collection_mode: str
    defaults: dict[str, Any]

    def validate(self, config: JobSource) -> None: ...
    def collect(self, config: JobSource, database_url: str) -> list[Any]: ...
    def normalize(self, config: JobSource, payload: dict[str, Any]) -> Job: ...


class RemotiveAdapter:
    collection_mode = "live"
    defaults = {"endpoint": "https://remotive.com/api/remote-jobs", "collection_strategy": "full_feed",
                "response_retention": "none", "min_interval_seconds": 21600, "settings": {}}

    def validate(self, config: JobSource) -> None:
        from jobsearch.collectors.source import REMOTIVE
        if config.endpoint != REMOTIVE.endpoint:
            raise ValueError("Remotive endpoint must be its documented public API URL")
        if config.min_interval_seconds < REMOTIVE.min_interval_seconds:
            raise ValueError("Remotive requires a minimum interval of 21600 seconds")
        if config.collection_strategy != "full_feed" or config.response_retention != "none":
            raise ValueError("Remotive supports full_feed with no automatic retention")
        if set(config.settings) - {"category", "search"}:
            raise ValueError("Remotive settings support only category and search")
        if any(not isinstance(v, str) or not v.strip() for v in config.settings.values()):
            raise ValueError("Remotive settings must be nonblank strings")

    def collect(self, config: JobSource, database_url: str) -> list[Any]:
        from jobsearch.collectors.remotive_collector import RemotiveCollector
        return RemotiveCollector(database_url, source_name=config.name).collect()

    def normalize(self, config: JobSource, payload: dict[str, Any]) -> Job:
        from jobsearch.normalization.remotive_normalizer import RemotiveJobNormalizer
        return RemotiveJobNormalizer.normalize(payload)


class FixtureAdapter:
    collection_mode = "fixture"
    defaults = {"endpoint": "", "collection_strategy": "local_file", "response_retention": "none",
                "min_interval_seconds": 0, "settings": {}}

    def validate(self, config: JobSource) -> None:
        if config.collection_strategy != "local_file" or config.response_retention != "none":
            raise ValueError("Fixture adapter requires local_file with no automatic retention")
        if config.min_interval_seconds != 0:
            raise ValueError("Local fixtures do not use HTTP request intervals")
        if config.endpoint:
            raise ValueError("Local fixtures use settings.path, not an endpoint")
        if set(config.settings) != {"path"} or not isinstance(config.settings["path"], str) or not config.settings["path"].strip():
            raise ValueError("Fixture settings require a nonblank path")

    def collect(self, config: JobSource, database_url: str) -> list[Any]:
        from jobsearch.collectors.json_fixture_collector import JsonFixtureCollector
        return JsonFixtureCollector(config.settings["path"]).collect()

    def normalize(self, config: JobSource, payload: dict[str, Any]) -> Job:
        from jobsearch.normalization.json_normalizer import JsonJobNormalizer
        return JsonJobNormalizer.normalize(payload)


ADAPTERS: dict[str, CollectorAdapter] = {"remotive": RemotiveAdapter(), "json_fixture": FixtureAdapter()}


def defaults_for(kind: str) -> dict:
    if not isinstance(kind, str) or kind not in ADAPTERS:
        raise ValueError(f"Unknown collector adapter: {kind}")
    return deepcopy(ADAPTERS[kind].defaults)


def adapter_for(config: JobSource) -> CollectorAdapter:
    if not isinstance(config.adapter_type, str):
        raise ValueError("adapter_type must be a registered name")
    try:
        adapter = ADAPTERS[config.adapter_type]
    except KeyError as exc:
        raise ValueError(f"Unknown collector adapter: {config.adapter_type}") from exc
    if not isinstance(config.enabled, bool):
        raise ValueError("enabled must be boolean")
    if isinstance(config.min_interval_seconds, bool) or not isinstance(config.min_interval_seconds, int):
        raise ValueError("min_interval_seconds must be an integer")
    if not isinstance(config.settings, dict):
        raise ValueError("settings must be an object")
    adapter.validate(config)
    return adapter
