from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.exc import IntegrityError

from jobsearch.evaluation import rules
from jobsearch.models import Applicant, Application, Job, JobEvaluation, ProcessingRun
from jobsearch.models.base import Base
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.evaluation_repository import EvaluationRepository


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def database(tmp_path):
    url = f"sqlite:///{tmp_path / 'evaluation.db'}"
    run_migrations(url)
    factory = build_session_factory(url)
    try:
        yield url, factory
    finally:
        factory.kw["bind"].dispose()


def make_job(**changes):
    return JsonJobNormalizer.normalize({"source_job_id": "example", "title": "Data Engineer",
        "company": "Fictional Company", "remote_type": "onsite", "location": "Example City",
        "salary_min": 100, "salary_max": 200, "salary_currency": "USD", "salary_period": "annual", **changes})


def test_existing_job_two_applicants_history_and_no_ai(database, monkeypatch):
    _, factory = database
    with factory() as session:
        session.add_all([make_job(), Applicant(id=17, full_name="Fictional Remote", remote_preference="remote"),
                         Applicant(id=23, full_name="Fictional Onsite", remote_preference="onsite")])
        session.commit()
    with factory() as session:
        repo = EvaluationRepository(session)
        rejected, summary = repo.evaluate_jobs(17)
        assert summary == {"keep": 0, "reject": 1, "review": 0, "unchanged": 0}
        original_id = rejected[0].id
        original_context = json.dumps(rejected[0].input_context, sort_keys=True)
        kept, summary = repo.evaluate_jobs(23)
        assert kept[0].decision == "keep" and summary["keep"] == 1
        assert repo.evaluate_jobs(17)[1]["unchanged"] == 1
        session.commit()
    with factory() as session:
        repo = EvaluationRepository(session)
        applicant = session.get(Applicant, 17)
        applicant.remote_preference = "onsite"
        session.commit()
        changed, summary = repo.evaluate_jobs(17)
        assert changed[0].decision == "keep" and summary["keep"] == 1
        job = session.query(Job).one()
        job.title = "Changed Title"
        session.commit()
        changed_job, _ = repo.evaluate_jobs(17)
        assert changed_job[0].input_context["job"]["title"] == "Changed Title"
        assert json.dumps(session.get(JobEvaluation, original_id).input_context, sort_keys=True) == original_context
        monkeypatch.setattr(rules, "RULES_VERSION", "preferences-test-v2")
        changed_rule, summary = repo.evaluate_jobs(17)
        assert changed_rule[0].rules_version == "preferences-test-v2" and summary["keep"] == 1
        assert repo.evaluate_jobs(17)[1]["unchanged"] == 1
        assert job.status == "new"
        session.commit()
    with factory() as session:
        assert session.query(Job).count() == 1
        assert session.query(ProcessingRun).count() == 0
        assert session.query(JobEvaluation).count() == 5
        for evaluation in session.query(JobEvaluation):
            assert evaluation.applicant_id in (17, 23) and evaluation.job_id is not None
            assert evaluation.evaluated_at is not None and evaluation.reasons
            assert evaluation.input_context and evaluation.rules_version
            for field in ("hireability_score", "career_value_score", "income_value_score",
                          "application_friction_score", "model_name", "estimated_ai_cost"):
                assert getattr(evaluation, field) is None


def test_snapshot_lists_reversion_and_database_uniqueness(database):
    _, factory = database
    with factory() as session:
        applicant = Applicant(id=9, full_name="Fictional", target_roles=["Engineer"])
        session.add_all([make_job(), applicant])
        session.commit()
        repo = EvaluationRepository(session)
        first, _ = repo.evaluate_jobs(9)
        applicant.target_roles.append("Scientist")
        session.commit()
        repo.evaluate_jobs(9)
        assert first[0].input_context["preferences"]["target_roles"] == ["Engineer"]
        applicant.target_roles.pop()
        session.commit()
        assert repo.evaluate_jobs(9)[1]["unchanged"] == 1
        session.add(JobEvaluation(job_id=first[0].job_id, applicant_id=9,
                                  input_fingerprint=first[0].input_fingerprint))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.query(JobEvaluation).count() == 2


def test_ingestion_keeps_unsuitable_jobs_and_evaluation_is_separate(database, monkeypatch):
    from jobsearch.scripts.run_fixture_ingestion import run_fixture_ingestion
    url, factory = database
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", url)
    assert run_fixture_ingestion(ROOT / "data/jobs_fixture_with_filtered.json") == 2
    with factory() as session:
        session.add(Applicant(id=31, full_name="Fictional", remote_preference="remote"))
        session.commit()
        jobs = session.query(Job).all()
        assert {job.remote_type for job in jobs} == {"remote", "onsite"}
        results, summary = EvaluationRepository(session).evaluate_jobs(31)
        session.commit()
        assert summary == {"keep": 1, "reject": 1, "review": 0, "unchanged": 0}
        assert session.query(Job).count() == 2
        run = session.query(ProcessingRun).one()
        assert run.jobs_new == 2 and run.records_invalid == 1 and run.jobs_scored == 0
        assert all(result.job.status == "new" for result in results)


def test_cli_results_filtering_summaries_and_invalid_ids(database):
    url, factory = database
    with factory() as session:
        session.add_all([Applicant(id=71, full_name="Fictional", remote_preference="remote"),
                         make_job(source_job_id="onsite"), make_job(source_job_id="remote", remote_type="remote"),
                         make_job(source_job_id="unknown", remote_type=None)])
        session.commit()
        one_job_id = session.query(Job).filter_by(source_job_id="onsite").one().id
    env = {**os.environ, "JOBSEARCH_DATABASE_URL": url}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "jobsearch.scripts.evaluation_cli", *args],
                              cwd=ROOT, env=env, capture_output=True, text=True)

    first = cli("evaluate", "--applicant-id", "71", "--job-id", str(one_job_id))
    assert first.returncode == 0, first.stderr
    assert "rejected=1" in first.stdout and "Job is onsite" in first.stdout
    result = cli("evaluate", "--applicant-id", "71")
    assert result.returncode == 0, result.stderr
    assert "kept=1 rejected=0 review-needed=1 unchanged/skipped=1" in result.stdout
    assert "Data Engineer" in result.stdout and "Fictional Company" in result.stdout
    again = cli("evaluate", "--applicant-id", "71")
    assert again.returncode == 0 and "unchanged/skipped=3" in again.stdout
    for decision in ("keep", "reject", "review"):
        listed = cli("list", "--applicant-id", "71", "--decision", decision)
        assert listed.returncode == 0, listed.stderr
        assert "Results: 1" in listed.stdout and f"| {decision}" in listed.stdout
    assert "Results: 3" in cli("list", "--applicant-id", "71").stdout
    for args in (("evaluate",), ("list",), ("evaluate", "--applicant-id", "0"),
                 ("evaluate", "--applicant-id", "no"), ("evaluate", "--applicant-id", "999"),
                 ("list", "--applicant-id", "999"), ("list", "--applicant-id", "71", "--decision", "maybe"),
                 ("evaluate", "--applicant-id", "71", "--job-id", "999"),
                 ("evaluate", "--applicant-id", "71", "--job-id", "-1")):
        invalid = cli(*args)
        assert invalid.returncode != 0 and "error:" in invalid.stderr
    with factory() as session:
        assert session.query(JobEvaluation).count() == 3


def test_invalid_applicant_checked_before_jobs(database, monkeypatch):
    _, factory = database
    with factory() as session:
        def no_jobs(*args, **kwargs):
            pytest.fail("Jobs must not be queried for a nonexistent applicant")
        monkeypatch.setattr(session, "scalars", no_jobs)
        with pytest.raises(ValueError, match="Applicant 999 does not exist"):
            EvaluationRepository(session).evaluate_jobs(999)


def test_period_input_round_trip(database):
    _, factory = database
    with factory() as session:
        applicant = ApplicantRepository(session).create_from_payload({"full_name": "Fictional", "salary_period": " Hourly "})
        job = make_job(salary_period="hourly")
        session.add(job)
        session.commit()
        applicant_id, job_id = applicant.id, job.id
    with factory() as session:
        assert session.get(Applicant, applicant_id).salary_period == "hourly"
        assert session.get(Job, job_id).salary_period == "hourly"


def test_upgrade_05_preserves_all_rows_and_unknown_periods(tmp_path):
    url = f"sqlite:///{tmp_path / 'old05.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url_override"] = url
    command.upgrade(config, "20260913_05")
    factory = build_session_factory(url)
    engine = factory.kw["bind"]
    metadata = MetaData()
    try:
        metadata.reflect(engine)
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(metadata.tables["jobs"].insert(), {"id": 9, "source": "legacy", "title": "Historical",
                "first_seen_at": now, "last_seen_at": now, "status": "new", "salary_min": 100, "salary_max": 200})
            connection.execute(metadata.tables["applicants"].insert(), {"id": 17, "full_name": "Fictional Legacy",
                "skills": [], "target_roles": [], "preferred_locations": [], "created_at": now, "updated_at": now})
            connection.execute(metadata.tables["applications"].insert(), {"id": 8, "job_id": 9, "status": "prepared", "applicant_id": 17})
            for applicant_id in (None, 17):
                connection.execute(metadata.tables["job_evaluations"].insert(), {"job_id": 9, "applicant_id": applicant_id,
                    "decision": "keep", "rejection_reason": "Historical reason", "model_name": "legacy-model", "hireability_score": 0.5})
            connection.execute(metadata.tables["processing_runs"].insert(), {"source": "legacy", "started_at": now,
                "jobs_seen": 1, "jobs_new": 1, "jobs_deduplicated": 0, "jobs_filtered": 0, "jobs_scored": 0})
            before = {name: connection.execute(select(table)).all() for name, table in metadata.tables.items() if name != "alembic_version"}
        run_migrations(url)
        current_metadata = MetaData()
        current_metadata.reflect(engine)
        with engine.connect() as connection:
            for name, rows in before.items():
                if name == "processing_runs":
                    table = current_metadata.tables[name]
                    assert connection.execute(select(*[column for column in table.c if column.name != "invalid_reason_counts"])).all() == rows
                else:
                    assert connection.execute(select(metadata.tables[name])).all() == rows
            assert connection.exec_driver_sql("SELECT salary_period FROM jobs").scalar() is None
            assert connection.exec_driver_sql("SELECT salary_period FROM applicants").scalar() is None
            assert connection.exec_driver_sql("SELECT rules_version FROM job_evaluations").scalar() is None
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_server_default": True}), Base.metadata) == []
        with factory() as session:
            results, summary = EvaluationRepository(session).evaluate_jobs(17)
            session.commit()
            assert summary["keep"] == 1 and results[0].rules_version == rules.RULES_VERSION
            assert session.query(JobEvaluation).count() == 3
    finally:
        engine.dispose()
