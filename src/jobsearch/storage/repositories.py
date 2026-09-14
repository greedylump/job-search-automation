from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun


class JobRepository:
    """Repository responsible for job insertion, lookup, and deduplication."""

    def __init__(self, session: Session):
        self.session = session

    def exists_by_source_key(self, source: str, source_job_id: str | None) -> bool:
        if not source or not source_job_id or not source_job_id.strip():
            return False
        statement = select(Job.id).where(Job.source == source, Job.source_job_id == source_job_id)
        return self.session.execute(statement).first() is not None

    def get_by_source_key(self, source: str, source_job_id: str | None) -> Job | None:
        if not source or not source_job_id or not source_job_id.strip():
            return None
        statement = select(Job).where(Job.source == source, Job.source_job_id == source_job_id)
        return self.session.execute(statement).scalar_one_or_none()

    def upsert_last_seen_at(self, job: Job, timestamp: datetime) -> None:
        existing = self.get_by_source_key(job.source, job.source_job_id)
        if existing:
            existing.last_seen_at = timestamp
            self.session.add(existing)

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

    def create(self, *, source: str, records_seen: int = 0, jobs_new: int = 0,
               jobs_deduplicated: int = 0, records_invalid: int = 0,
               jobs_scored: int = 0, ai_cost: float | None = None,
               status: str = "running", error_message: str | None = None,
               invalid_reason_counts: dict[str, int] | None = None) -> ProcessingRun:
        run = ProcessingRun(
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            source=source,
            status=status,
            error_message=error_message,
            records_seen=records_seen,
            jobs_new=jobs_new,
            jobs_deduplicated=jobs_deduplicated,
            records_invalid=records_invalid,
            invalid_reason_counts=dict(invalid_reason_counts) if invalid_reason_counts is not None else None,
            jobs_scored=jobs_scored,
            ai_cost=ai_cost,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish(self, run: ProcessingRun, *, status: str = "completed", error_message: str | None = None,
               records_seen: int = 0, jobs_new: int = 0, jobs_deduplicated: int = 0,
               records_invalid: int = 0, jobs_scored: int = 0, ai_cost: float | None = None,
               invalid_reason_counts: dict[str, int] | None = None) -> ProcessingRun:
        run.status = status
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        run.records_seen = records_seen
        run.jobs_new = jobs_new
        run.jobs_deduplicated = jobs_deduplicated
        run.records_invalid = records_invalid
        run.invalid_reason_counts = dict(invalid_reason_counts) if invalid_reason_counts is not None else None
        run.jobs_scored = jobs_scored
        run.ai_cost = ai_cost
        self.session.add(run)
        self.session.flush()
        return run
