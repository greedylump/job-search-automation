from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from jobsearch.collectors.json_fixture_collector import JsonFixtureCollector
from jobsearch.config.settings import get_settings
from jobsearch.filtering.filters import JobFilter
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import get_session
from jobsearch.storage.repositories import JobRepository, ProcessingRunRepository

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def run_fixture_ingestion(fixture_path: str | Path = "data/jobs_fixture.json") -> int:
    """Run the sample full pipeline: collect -> normalize -> dedupe -> filter -> store metrics."""
    settings = get_settings()
    run_migrations(settings.database_url)

    session = get_session(settings.database_url)
    try:
        run_repo = ProcessingRunRepository(session)
        processing_run = run_repo.create(source="fixture_json")

        collector = JsonFixtureCollector(fixture_path)
        raw_jobs = collector.collect()
        normalized_jobs = [JsonJobNormalizer.normalize(job, source="fixture_json") for job in raw_jobs]

        jobs_seen = len(normalized_jobs)
        jobs_new = 0
        jobs_deduplicated = 0
        jobs_filtered = 0

        # Step 1: deduplicate by the source + source_job_id key requested by the project scope.
        candidates = []
        for job in normalized_jobs:
            if JobRepository(session).exists_by_source_key(job.source, job.source_job_id):
                jobs_deduplicated += 1
                continue
            candidates.append(job)

        # Step 2: apply deterministic placeholder rules.
        filtered_jobs = JobFilter().filter(candidates)
        jobs_filtered = len(candidates) - len(filtered_jobs)

        # Step 3: persist accepted jobs and corresponding ProcessingRun metrics.
        for job in filtered_jobs:
            session.add(job)
            jobs_new += 1

        # Explicitly make the AI-free first milestone metrics deterministic and record them.
        processing_run.jobs_seen = jobs_seen
        processing_run.jobs_new = jobs_new
        processing_run.jobs_deduplicated = jobs_deduplicated
        processing_run.jobs_filtered = jobs_filtered
        processing_run.jobs_scored = 0
        processing_run.ai_cost = 0.0
        processing_run.completed_at = datetime.now(timezone.utc)

        session.commit()
        logger.info(
            "Processed %s jobs from %s; dedup=%s; filtered=%s; inserted=%s",
            jobs_seen,
            fixture_path,
            jobs_deduplicated,
            jobs_filtered,
            jobs_new,
        )
        return jobs_new
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run_fixture_ingestion()
