from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from jobsearch.collectors.json_fixture_collector import JsonFixtureCollector
from jobsearch.config.settings import get_settings
from jobsearch.filtering.filters import JobFilter
from jobsearch.models.processing_run import ProcessingRun
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import close_session, get_session
from jobsearch.storage.repositories import JobRepository, ProcessingRunRepository

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def _finish_processing_run_for_failure(
    database_url: str,
    processing_run_id: int,
    *,
    jobs_seen: int,
    jobs_deduplicated: int,
    jobs_filtered: int,
    jobs_scored: int,
    ai_cost: float,
    error_message: str,
) -> None:
    """Persist the failure state in a fresh session so rollback does not hide the run row."""
    fail_session = get_session(database_url)
    try:
        run = fail_session.get(ProcessingRun, processing_run_id)
        if run is None:
            return
        run.status = "failed"
        run.error_message = error_message
        run.jobs_seen = jobs_seen
        run.jobs_new = 0
        run.jobs_deduplicated = jobs_deduplicated
        run.jobs_filtered = jobs_filtered
        run.jobs_scored = jobs_scored
        run.ai_cost = ai_cost
        run.completed_at = datetime.now(timezone.utc)
        fail_session.add(run)
        fail_session.commit()
    except Exception:
        fail_session.rollback()
    finally:
        close_session(fail_session)


def run_fixture_ingestion(fixture_path: str | Path = "data/jobs_fixture.json") -> int:
    """Run the sample full pipeline: collect -> normalize -> dedupe -> filter -> store metrics."""
    settings = get_settings()
    run_migrations(settings.database_url)

    session = get_session(settings.database_url)
    processing_run = None
    processing_run_id = None
    jobs_seen = 0
    jobs_new = 0
    jobs_deduplicated = 0
    jobs_filtered = 0
    jobs_scored = 0
    ai_cost = 0.0

    try:
        run_repo = ProcessingRunRepository(session)
        processing_run = run_repo.create(source="fixture_json")
        session.commit()
        processing_run_id = processing_run.id

        collector = JsonFixtureCollector(fixture_path)
        raw_jobs = collector.collect()

        repo = JobRepository(session)
        seen_keys_in_batch: set[tuple[str, str]] = set()
        normalized_jobs: list = []

        # Normalize and verify source-key policy before adding any row.
        for payload in raw_jobs:
            job = JsonJobNormalizer.normalize(payload, source="fixture_json")
            jobs_seen += 1

            if not job.source_job_id or not job.source_job_id.strip():
                jobs_filtered += 1
                continue

            key = (job.source, job.source_job_id)
            if key in seen_keys_in_batch:
                jobs_deduplicated += 1
                continue
            seen_keys_in_batch.add(key)

            if repo.exists_by_source_key(job.source, job.source_job_id):
                jobs_deduplicated += 1
                repo.upsert_last_seen_at(job, datetime.now(timezone.utc))
                continue

            normalized_jobs.append(job)

        # Reject invalid source records only; suitability is evaluated separately.
        filtered_jobs = JobFilter().filter(normalized_jobs)
        jobs_filtered += len(normalized_jobs) - len(filtered_jobs)

        # Persist accepted jobs.
        for job in filtered_jobs:
            session.add(job)
            jobs_new += 1

        # Record the metrics into the ProcessingRun row.
        processing_run.jobs_seen = jobs_seen
        processing_run.jobs_new = jobs_new
        processing_run.jobs_deduplicated = jobs_deduplicated
        processing_run.jobs_filtered = jobs_filtered
        processing_run.jobs_scored = jobs_scored
        processing_run.ai_cost = ai_cost
        processing_run.completed_at = datetime.now(timezone.utc)
        processing_run.status = "completed"
        processing_run.error_message = None

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
    except Exception as exc:
        logger.exception("Fixture ingestion failed: %s", exc)
        try:
            session.rollback()
        except Exception:
            pass
        if processing_run_id is not None:
            _finish_processing_run_for_failure(
                settings.database_url,
                processing_run_id,
                jobs_seen=jobs_seen,
                jobs_deduplicated=jobs_deduplicated,
                jobs_filtered=jobs_filtered,
                jobs_scored=jobs_scored,
                ai_cost=ai_cost,
                error_message=str(exc),
            )
        raise
    finally:
        close_session(session)


if __name__ == "__main__":
    run_fixture_ingestion()
