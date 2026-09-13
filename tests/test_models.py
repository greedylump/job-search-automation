from __future__ import annotations

from datetime import datetime, timezone

from jobsearch.models.job import Job
from jobsearch.models.processing_run import ProcessingRun


def test_job_model_can_be_created() -> None:
    job = Job(
        source="fixture_json",
        source_job_id="job-1",
        company="Example",
        title="Python Developer",
        location="Remote",
        remote_type="remote",
        employment_type="full_time",
        salary_min=120000,
        salary_max=150000,
        salary_currency="USD",
        description="Backend work",
        job_url="https://example.com/jobs/job-1",
        apply_url="https://example.com/apply/job-1",
        ats_type="greenhouse",
        posted_at=datetime.now(timezone.utc),
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        status="new",
    )

    assert job.source == "fixture_json"
    assert job.title == "Python Developer"
    assert job.status == "new"


def test_processing_run_model_can_be_created() -> None:
    run = ProcessingRun(
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        source="fixture_json",
        jobs_seen=2,
        jobs_new=1,
        jobs_deduplicated=1,
        jobs_filtered=0,
        jobs_scored=0,
        ai_cost=0,
    )

    assert run.source == "fixture_json"
    assert run.jobs_seen == 2
    assert run.jobs_new == 1
