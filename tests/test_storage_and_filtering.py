from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jobsearch.filtering.filters import JobFilter, MinimumTitleRule
from jobsearch.models.base import Base
from jobsearch.models.job import Job
from jobsearch.storage.repositories import JobRepository


def test_repository_deduplicates_by_source_and_source_job_id() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()

    try:
        repo = JobRepository(session)

        job_one = Job(
            source="fixture_json",
            source_job_id="job-123",
            title="Python Developer",
            company="Example",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            status="new",
        )

        inserted = repo.insert_if_new(job_one)
        assert inserted is True

        duplicate = Job(
            source="fixture_json",
            source_job_id="job-123",
            title="Python Developer",
            company="Example",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            status="new",
        )

        inserted_again = repo.insert_if_new(duplicate)
        assert inserted_again is False

        session.commit()
        assert repo.get_by_source_key("fixture_json", "job-123") is not None
    finally:
        session.close()
        engine.dispose()


def test_filter_rules_accept_and_reject_jobs_deterministically() -> None:
    filterer = JobFilter([MinimumTitleRule()])

    valid_job = Job(
        source="fixture_json",
        source_job_id="keep",
        title="Engineer",
        company="Example",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        status="new",
    )

    invalid_job = Job(
        source="fixture_json",
        source_job_id="drop",
        title=" ",
        company="Example",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        status="new",
    )

    result = filterer.filter([valid_job, invalid_job])
    assert len(result) == 1
    assert result[0].source_job_id == "keep"
