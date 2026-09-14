from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonFixtureCollector:
    """Read all fixture entries, preserving malformed records for ingestion metrics."""

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)

    def collect(self) -> list[Any]:
        with self.fixture_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("jobs")
            if isinstance(items, list):
                return items
        raise ValueError(f"Unsupported fixture format in {self.fixture_path}")
