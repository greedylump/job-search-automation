from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun


class JobRepository:
    """Repository responsible for job insertion, lookup, and deduplication."""

    def __init__(self, session: Session):
        self.session = session

    def exists_by_source_key(self, source: str, source_job_id: str | None) -> bool:
        if not source or not source_job_id:
            return False
        statement = select(Job.id).where(Job.source == source, Job.source_job_id == source_job_id)
        return self.session.execute(statement).first() is not None

    def get_by_source_key(self, source: str, source_job_id: str | None) -> Job | None:
        if not source or not source_job_id:
            return None
        statement = select(Job).where(Job.source == source, Job.source_job_id == source_job_id)
        return self.session.execute(statement).scalar_one_or_none()

    def insert_if_new(self, job: Job) -> bool:
        """Insert a job when the deduplication key is not already present; return True when inserted."""
        if self.exists_by_source_key(job.source, job.source_job_id):
            return False
        self.session.add(job)
        self.session.flush()
        return True

    def list(self, limit: int | None = None) -> list[Job]:
        statement = select(Job).order_by(Job.first_seen_at.desc())
        if limit:
            statement = statement.limit(limit)
        return list(self.session.execute(statement).scalars().all())


class ProcessingRunRepository:
    """Repository for processing metrics and run bookkeeping."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, *, source: str, jobs_seen: int = 0, jobs_new: int = 0,
               jobs_deduplicated: int = 0, jobs_filtered: int = 0,
               jobs_scored: int = 0, ai_cost: float | None = None) -> ProcessingRun:
        run = ProcessingRun(
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            source=source,
            jobs_seen=jobs_seen,
            jobs_new=jobs_new,
            jobs_deduplicated=jobs_deduplicated,
            jobs_filtered=jobs_filtered,
            jobs_scored=jobs_scored,
            ai_cost=ai_cost,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish(self, run: ProcessingRun) -> ProcessingRun:
        run.completed_at = datetime.now(timezone.utc)
        self.session.flush()
        return run
