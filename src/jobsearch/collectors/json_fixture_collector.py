from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonFixtureCollector:
    """Read jobs from a local JSON fixture that contains a list of raw job objects."""

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)

    def collect(self) -> list[dict[str, Any]]:
        with self.fixture_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("jobs")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        raise ValueError(f"Unsupported fixture format in {self.fixture_path}")
