from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from urllib.parse import urlencode

from jobsearch.collectors.source import REMOTIVE
from jobsearch.collectors.http_client import fetch_records
from jobsearch.storage.source_repository import SourceRepository, utcnow

API_URL = REMOTIVE.endpoint
MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class RemotiveCollector:
    """Fetch only when a persistent request slot is available; never read a cache."""

    def __init__(self, database_url: str, snapshot_path: str | Path | None = None, *, source_name: str = "remotive"):
        self.state = SourceRepository(database_url)
        self.source_name = source_name
        self.snapshot_path = Path(snapshot_path) if snapshot_path is not None else None

    @staticmethod
    def _decode(raw: bytes) -> list[Any]:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Remotive response exceeds the 20 MiB limit")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Remotive returned invalid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Remotive response must contain a jobs array")
        return data["jobs"]

    @classmethod
    def replay(cls, path: str | Path) -> list[Any]:
        with Path(path).open("rb") as handle:
            return cls._decode(handle.read(MAX_RESPONSE_BYTES + 1))

    def collect(self) -> list[Any]:
        if self.snapshot_path is not None and self.snapshot_path.exists():
            raise FileExistsError(f"Snapshot already exists: {self.snapshot_path}")
        source = self.state.reserve(REMOTIVE if self.source_name == "remotive" else self.source_name)
        query = urlencode(source.settings)
        endpoint = source.endpoint + ("?" + query if query else "")
        return fetch_records(source=source, state=self.state, endpoint=endpoint,
                             decode=self._decode, opener=urlopen, now=utcnow,
                             max_bytes=MAX_RESPONSE_BYTES, snapshot_path=self.snapshot_path)
