from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jobsearch.models.job import Job


class JsonJobNormalizer:
    """Normalize a fixture JSON object into the canonical Job ORM model."""

    @staticmethod
    def normalize(payload: dict[str, Any], source: str = "fixture_json") -> Job:
        posted_at = payload.get("posted_at")
        if isinstance(posted_at, str):
            try:
                posted_at_value = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            except ValueError:
                posted_at_value = None
        else:
            posted_at_value = None

        now = datetime.now(timezone.utc)
        return Job(
            source=source,
            source_job_id=str(payload.get("source_job_id") or payload.get("id") or payload.get("job_id") or ""),
            company=payload.get("company"),
            title=payload.get("title"),
            location=payload.get("location"),
            remote_type=payload.get("remote_type"),
            employment_type=payload.get("employment_type"),
            salary_min=payload.get("salary_min"),
            salary_max=payload.get("salary_max"),
            salary_currency=payload.get("salary_currency"),
            description=payload.get("description"),
            job_url=payload.get("job_url"),
            apply_url=payload.get("apply_url"),
            ats_type=payload.get("ats_type"),
            posted_at=posted_at_value,
            first_seen_at=now,
            last_seen_at=now,
            status="new",
        )
