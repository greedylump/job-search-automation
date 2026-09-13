from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from jobsearch.collectors.json_fixture_collector import JsonFixtureCollector
from jobsearch.config.settings import settings
from jobsearch.filtering.filters import JobFilter
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.storage.database import SessionLocal, init_db
from jobsearch.storage.repositories import JobRepository, ProcessingRunRepository
from jobsearch.models.job import Job

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def run_fixture_ingestion(fixture_path: str | Path = "data/jobs_fixture.json") -> int:
    """Run the sample full pipeline: collect -> normalize -> dedupe -> filter -> store metrics."""
    init_db(settings.database_url)

    session = SessionLocal()
    try:
        run_repo = ProcessingRunRepository(session)
        processing_run = run_repo.create(source="fixture_json")

        collector = JsonFixtureCollector(fixture_path)
        raw_jobs = collector.collect()

        job_repo = JobRepository(session)
        normalized_jobs = [JsonJobNormalizer.normalize(job, source="fixture_json") for job in raw_jobs]

        jobs_seen = len(normalized_jobs)
        jobs_new = 0
        jobs_deduplicated = 0
        jobs_filtered = 0

        for job in normalized_jobs:
            if job_repo.exists_by_source_key(job.source, job.source_job_id):
                jobs_deduplicated += 1
                continue
            if not job.title or not job.title.strip():
                jobs_filtered += 1
                continue
            session.add(job)
            jobs_new += 1

        filtered_jobs = JobFilter().filter([job for job in session.new if isinstance(job, Job)])
        # Filter count is represented by jobs rejected by the current deterministic rules.
        jobs_filtered = jobs_seen - len(filtered_jobs) - jobs_deduplicated

        processing_run.jobs_seen = jobs_seen
        processing_run.jobs_new = jobs_new
        processing_run.jobs_deduplicated = jobs_deduplicated
        processing_run.jobs_filtered = jobs_filtered
        processing_run.jobs_scored = 0
        processing_run.ai_cost = 0
        processing_run.completed_at = datetime.now(timezone.utc)

        session.commit()
        logger.info("Processed %s jobs from %s", jobs_seen, fixture_path)
        return len(filtered_jobs)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run_fixture_ingestion()
