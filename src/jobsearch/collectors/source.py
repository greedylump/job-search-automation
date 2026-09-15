from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    endpoint: str
    collection_strategy: str
    response_retention: str
    min_interval_seconds: int


class SourceSkipped(Exception):
    def __init__(self, reason: str, next_allowed_at: datetime | None, *, status: str = "skipped"):
        super().__init__(reason)
        self.next_allowed_at = next_allowed_at
        self.status = status


REMOTIVE = SourceDefinition(
    name="remotive", endpoint="https://remotive.com/api/remote-jobs",
    collection_strategy="full_feed", response_retention="none",
    min_interval_seconds=6 * 60 * 60,
)
