from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from collections.abc import Callable
from typing import Any
from jobsearch.collectors.source import SourceSkipped
from jobsearch.storage.collection_control import ensure_collection_allowed
from jobsearch.collectors.run_context import processing_run_id as active_run_id
from jobsearch.collectors.run_context import collector_lease
from jobsearch.collectors.pagination import CollectionBatch
from jobsearch.models import JobSource, RequestBudget
from jobsearch.storage.budget_repository import eligible_at
from jobsearch.storage import source_repository

from jobsearch.config.settings import get_settings
from jobsearch.filtering.filters import JobFilter
from jobsearch.models.processing_run import ProcessingRun
from jobsearch.models.job import Job
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
    records_seen: int,
    jobs_deduplicated: int,
    records_invalid: int,
    invalid_reason_counts: dict[str, int],
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
        run.records_seen = records_seen
        run.jobs_new = 0
        run.jobs_deduplicated = jobs_deduplicated
        run.records_invalid = records_invalid
        run.invalid_reason_counts = dict(invalid_reason_counts)
        run.jobs_scored = jobs_scored
        run.ai_cost = ai_cost
        run.completed_at = datetime.now(timezone.utc)
        fail_session.add(run)
        fail_session.commit()
    except Exception:
        fail_session.rollback()
    finally:
        close_session(fail_session)


def run_ingestion(*, source: str, collect: Callable[[], list[Any] | CollectionBatch],
                  normalize: Callable[[dict[str, Any]], Job],
                  database_url: str | None = None, collection_mode: str = "fixture") -> ProcessingRun:
    """Collect and store one source batch, recording durable success/failure metrics."""
    settings = get_settings()
    database_url = database_url or settings.database_url
    run_migrations(database_url)

    session = get_session(database_url)
    processing_run = None
    processing_run_id = None
    records_seen = 0
    jobs_new = 0
    jobs_deduplicated = 0
    records_invalid = 0
    invalid_reason_counts = {"non_object": 0, "missing_source_id": 0, "invalid_title": 0}
    jobs_scored = 0
    ai_cost = 0.0

    try:
        run_repo = ProcessingRunRepository(session)
        processing_run = run_repo.create(source=source, invalid_reason_counts=invalid_reason_counts, ai_cost=0.0)
        processing_run.collection_mode = collection_mode
        session.commit()
        processing_run_id = processing_run.id

        token = active_run_id.set(processing_run_id)
        try:
            ensure_collection_allowed(database_url)
            raw_jobs = collect()
        finally:
            active_run_id.reset(token)

        batch = raw_jobs if isinstance(raw_jobs, CollectionBatch) else CollectionBatch(raw_jobs, True, pages=1 if collection_mode == "live" else 0)
        raw_jobs = batch.records
        processing_run.pages_collected = batch.pages
        # No jobs or checkpoints are written if storage became unsafe in flight.
        # Request history is already durable; the old cursor permits safe replay.
        ensure_collection_allowed(database_url)
        session.execute(text("BEGIN IMMEDIATE"))
        source_row = session.get(JobSource, source)
        lease = collector_lease.get()
        if lease is not None and (source_row.lease_token != lease or
                source_row.lease_expires_at <= source_repository.utcnow()):
            raise RuntimeError("Collector lease expired before ingestion commit")

        repo = JobRepository(session)
        seen_keys_in_batch: set[tuple[str, str]] = set()
        normalized_jobs: list[Job] = []

        # Normalize and verify source-key policy before adding any row.
        for payload in raw_jobs:
            records_seen += 1
            if not isinstance(payload, dict):
                records_invalid += 1
                invalid_reason_counts["non_object"] += 1
                continue

            job = normalize(payload)

            if not job.source_job_id or not job.source_job_id.strip():
                records_invalid += 1
                invalid_reason_counts["missing_source_id"] += 1
                continue

            key = (job.source, job.source_job_id)
            if key in seen_keys_in_batch:
                jobs_deduplicated += 1
                continue
            seen_keys_in_batch.add(key)

            if repo.exists_by_source_key(job.source, job.source_job_id):
                jobs_deduplicated += 1
                if collection_mode != "replay":
                    repo.upsert_last_seen_at(job, datetime.now(timezone.utc))
                continue

            normalized_jobs.append(job)

        # Reject invalid source records only; suitability is evaluated separately.
        filtered_jobs = JobFilter().filter(normalized_jobs)
        records_invalid += len(normalized_jobs) - len(filtered_jobs)
        invalid_reason_counts["invalid_title"] = len(normalized_jobs) - len(filtered_jobs)

        # Persist accepted jobs.
        for job in filtered_jobs:
            session.add(job)
            jobs_new += 1

        # Record the metrics into the ProcessingRun row.
        processing_run.records_seen = records_seen
        processing_run.jobs_new = jobs_new
        processing_run.jobs_deduplicated = jobs_deduplicated
        processing_run.records_invalid = records_invalid
        processing_run.invalid_reason_counts = dict(invalid_reason_counts)
        processing_run.jobs_scored = jobs_scored
        processing_run.ai_cost = ai_cost
        processing_run.completed_at = datetime.now(timezone.utc)
        processing_run.status = "completed" if batch.complete else ("partial" if batch.pages else "deferred")
        processing_run.pages_collected = batch.pages
        if not batch.complete:
            processing_run.skip_reason = batch.reason
            processing_run.next_eligible_at = batch.next_eligible_at
        processing_run.error_message = None

        if source_row is not None and collection_mode != "replay":
            now = source_repository.utcnow()
            if batch.complete:
                source_row.continuation = None
                source_row.last_complete_refresh_at = now
                source_row.next_due_at = now + timedelta(seconds=source_row.refresh_interval_seconds)
            else:
                source_row.continuation = {"cursor": batch.next_cursor} if batch.next_cursor is not None else None
                source_row.next_due_at = max(now + timedelta(minutes=5), batch.next_eligible_at or now)
                budget = session.get(RequestBudget, source_row.budget_name) if source_row.budget_name else None
                if budget is not None:
                    source_row.next_due_at = max(source_row.next_due_at, eligible_at(session, budget, now) or now)
                processing_run.next_eligible_at = source_row.next_due_at

        session.commit()
        logger.info(
            "Processed %s records from %s; dedup=%s; invalid=%s; inserted=%s",
            records_seen,
            source,
            jobs_deduplicated,
            records_invalid,
            jobs_new,
        )
        logger.info(
            "Invalid records: non-object=%s; missing ID=%s; invalid title=%s",
            invalid_reason_counts["non_object"],
            invalid_reason_counts["missing_source_id"],
            invalid_reason_counts["invalid_title"],
        )
        return processing_run
    except SourceSkipped as exc:
        if exc.status == "not_modified" and collector_lease.get() is not None:
            session.execute(text("BEGIN IMMEDIATE"))
            current = session.get(JobSource, source)
            now = source_repository.utcnow()
            if current.lease_token == collector_lease.get() and current.lease_expires_at > now:
                current.last_complete_refresh_at = now
                current.next_due_at = now + timedelta(seconds=current.refresh_interval_seconds)
            else:
                exc = SourceSkipped("Collector lease expired before completion", None)
        processing_run.status = exc.status
        processing_run.skip_reason = str(exc)
        processing_run.next_eligible_at = exc.next_allowed_at
        processing_run.completed_at = datetime.now(timezone.utc)
        session.commit()
        logger.info("Skipped %s: %s; next eligible UTC=%s", source, exc, exc.next_allowed_at)
        return processing_run
    except Exception as exc:
        logger.exception("Ingestion failed for %s: %s", source, exc)
        try:
            session.rollback()
        except Exception:
            pass
        if processing_run_id is not None:
            _finish_processing_run_for_failure(
                database_url,
                processing_run_id,
                records_seen=records_seen,
                jobs_deduplicated=jobs_deduplicated,
                records_invalid=records_invalid,
                invalid_reason_counts=invalid_reason_counts,
                jobs_scored=jobs_scored,
                ai_cost=ai_cost,
                error_message=str(exc),
            )
        raise
    finally:
        close_session(session)


