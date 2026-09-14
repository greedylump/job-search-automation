from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobsearch.models import Applicant, Application, JobEvaluation, Job, ProcessingRun
from jobsearch.models.base import Base
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.applicant_repository import ApplicantRepository

ROOT = Path(__file__).resolve().parents[1]
HEAD = "20260914_08"


@pytest.fixture
def database(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    run_migrations(url)
    factory = build_session_factory(url)
    try:
        yield url, factory
    finally:
        factory.kw["bind"].dispose()


def test_mutations_timestamps_and_independent_defaults(database, monkeypatch):
    import jobsearch.models.applicant as applicant_module

    # Advance a controlled clock between writes instead of relying on OS resolution.
    current_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(tz):
            return current_time.astimezone(tz)

    monkeypatch.setattr(applicant_module, "datetime", Clock)
    _, factory = database
    with factory() as session:
        first = Applicant(id=17, full_name="Fictional One")
        second = Applicant(full_name="Fictional Two")
        session.add_all([first, second])
        session.commit()
        original = first.updated_at.replace(tzinfo=None)
        created = first.created_at.replace(tzinfo=None)
        assert original == created == current_time.replace(tzinfo=None)
    current_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with factory() as session:
        first = session.get(Applicant, 17)
        first.location = "Example City"
        session.commit()
    with factory() as session:
        first = session.get(Applicant, 17)
        assert first.updated_at > original
        assert first.updated_at == current_time.replace(tzinfo=None)
        previous = first.updated_at
        current_time = datetime(2026, 1, 3, tzinfo=timezone.utc)
        for field in ApplicantRepository.LIST_FIELDS:
            getattr(first, field).append("Example")
        session.commit()
    with factory() as session:
        first = session.get(Applicant, 17)
        second = session.query(Applicant).filter(Applicant.id != 17).one()
        assert first.updated_at > previous
        assert first.updated_at == current_time.replace(tzinfo=None)
        assert first.created_at == created
        for field in ApplicantRepository.LIST_FIELDS:
            assert getattr(first, field) == ["Example"]
            assert getattr(second, field) == []


INVALID = [({"full_name": value}) for value in (None, " ", 42, True)]
INVALID += [{field: 123} for field in sorted(ApplicantRepository.TEXT_FIELDS)]
INVALID += [{field: value} for field in sorted(ApplicantRepository.LIST_FIELDS) for value in (None, "Python", [1])]
INVALID += [{"minimum_salary": value} for value in (-1, True, "10", float("inf"), float("nan"), 10**400)]
INVALID += [{field: "bad"} for field in ("id", "created_at", "updated_at", "unknown")]
INVALID += [{"remote_preference": "sometimes"}, {"email": "invalid"}]


@pytest.mark.parametrize("payload", INVALID)
def test_invalid_create_and_update(payload):
    repo = ApplicantRepository(None)
    with pytest.raises(ValueError):
        repo.create_from_payload({"full_name": "Fictional", **payload})
    with pytest.raises(ValueError):
        repo.update_from_payload(17, payload)


def test_partial_update_and_normalization(database):
    _, factory = database
    with factory() as session:
        repo = ApplicantRepository(session)
        with pytest.raises(ValueError, match="full_name"):
            repo.create_from_payload({})
        for payload in ([], None, "name"):
            with pytest.raises(ValueError, match="object"):
                repo.validate_payload(payload)
        applicant = repo.create_from_payload({"full_name": " Fictional ", "remote_preference": " REMOTE "})
        for remote in (" Hybrid ", "ONSITE", "any", None):
            repo.update_from_payload(applicant.id, {"remote_preference": remote, "minimum_salary": 0, "skills": []})
            assert applicant.remote_preference == (remote.strip().lower() if remote else None)
        repo.update_from_payload(applicant.id, {"phone": None})
        assert applicant.full_name == "Fictional"
        with pytest.raises(ValueError, match="does not exist"):
            repo.update_from_payload(9999, {})
        session.commit()


def test_schema_and_relationships(database):
    _, factory = database
    engine = factory.kw["bind"]
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection, opts={"compare_server_default": True}), Base.metadata) == []
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        for table in ("applications", "job_evaluations"):
            assert any(index["column_names"] == ["applicant_id"] for index in inspect(connection).get_indexes(table))
    assert "applicant_id" not in Job.__table__.columns
    with factory() as session:
        now = datetime.now(timezone.utc)
        job = Job(source="test", first_seen_at=now, last_seen_at=now)
        applicant = Applicant(id=23, full_name="Fictional")
        application = Application(job=job, applicant=applicant)
        evaluation = JobEvaluation(job=job, applicant=applicant)
        session.add_all([application, evaluation])
        session.commit()
        application.applicant_id = 99999
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        evaluation.applicant_id = 99999
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.delete(applicant)
        session.commit()
    with factory() as session:
        assert session.query(Application).one().applicant_id is None
        assert session.query(JobEvaluation).one().applicant_id is None
        assert session.query(Job).count() == 1
        run = ProcessingRun(started_at=datetime.now(timezone.utc), source="test")
        session.add(run)
        session.commit()
        assert run.status == "running"


def test_upgrade_original_03_preserves_records(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url_override"] = url
    command.upgrade(config, "20260912_03")
    factory = build_session_factory(url)
    engine = factory.kw["bind"]
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO jobs (id,source,first_seen_at,last_seen_at,status) VALUES (7,'test','2026-01-01','2026-01-01','new')")
            connection.exec_driver_sql("INSERT INTO applications (id,job_id,status) VALUES (8,7,'prepared')")
            connection.exec_driver_sql("INSERT INTO job_evaluations (id,job_id,decision) VALUES (9,7,'keep')")
            for status in (None, "failed", "running"):
                connection.exec_driver_sql("INSERT INTO processing_runs (started_at,source,jobs_seen,jobs_new,jobs_deduplicated,jobs_filtered,jobs_scored) VALUES ('2026-01-01','test',1,1,0,0,0)")
                if status:
                    connection.execute(text("UPDATE processing_runs SET status=:status WHERE id=(SELECT MAX(id) FROM processing_runs)"), {"status": status})
            before = {table: connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in ("jobs", "applications", "job_evaluations", "processing_runs")}
            assert before["processing_runs"][0][-2] == "completed"
        run_migrations(url)
        with engine.begin() as connection:
            for table, rows in before.items():
                after = connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall()
                assert [tuple(row[:len(rows[0])]) for row in after] == [tuple(row) for row in rows]
                if table in ("applications", "job_evaluations"):
                    assert connection.exec_driver_sql(f"SELECT applicant_id FROM {table}").scalar() is None
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_server_default": True}), Base.metadata) == []
            connection.exec_driver_sql("INSERT INTO processing_runs (started_at,source,records_seen,jobs_new,jobs_deduplicated,records_invalid,jobs_scored) VALUES ('2026-01-01','test',0,0,0,0,0)")
            assert connection.exec_driver_sql("SELECT status FROM processing_runs ORDER BY id DESC LIMIT 1").scalar() == "running"
    finally:
        engine.dispose()


def test_metric_rename_preserves_counts_in_both_directions(tmp_path):
    url = f"sqlite:///{tmp_path / 'metrics.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url_override"] = url
    command.upgrade(config, "20260913_06")
    engine = build_session_factory(url).kw["bind"]
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO processing_runs (started_at,source,jobs_seen,jobs_new,jobs_deduplicated,jobs_filtered,jobs_scored,ai_cost,status,error_message) VALUES ('2026-01-01','test',13,5,3,5,0,0,'failed','example')")
            before = connection.exec_driver_sql("SELECT * FROM processing_runs").all()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            after = connection.exec_driver_sql("SELECT * FROM processing_runs").all()
            assert [tuple(row[:-1]) for row in after] == [tuple(row) for row in before]
            assert connection.exec_driver_sql("SELECT invalid_reason_counts FROM processing_runs").scalar() is None
            columns = {column["name"] for column in inspect(connection).get_columns("processing_runs")}
            assert {"records_seen", "records_invalid"} <= columns
            assert not {"jobs_seen", "jobs_filtered"} & columns
            assert connection.exec_driver_sql("SELECT records_seen, records_invalid FROM processing_runs").one() == (13, 5)
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_server_default": True}), Base.metadata) == []
        command.downgrade(config, "20260913_06")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM processing_runs").all() == before
            assert connection.exec_driver_sql("SELECT jobs_seen, jobs_filtered FROM processing_runs").one() == (13, 5)
    finally:
        engine.dispose()


def test_actual_url_precedence(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.db"
    shell = tmp_path / "shell.db"
    dotenv = tmp_path / "dotenv.db"
    (tmp_path / ".env").write_text(f"JOBSEARCH_DATABASE_URL=sqlite:///{dotenv}\n")
    # Use a standalone Alembic config in the temporary working directory.
    config = tmp_path / "alembic.ini"
    config.write_text(f"[alembic]\nscript_location = {ROOT / 'alembic'}\nsqlalchemy.url = sqlite:///{tmp_path / 'fallback.db'}\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["JOBSEARCH_DATABASE_URL"] = f"sqlite:///{shell}"
    script = "from jobsearch.scripts.init_db import run_migrations; run_migrations(" + repr(f"sqlite:///{explicit}") + ")"
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", f"sqlite:///{shell}")
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert explicit.exists() and not shell.exists() and not dotenv.exists()
    assert os.environ["JOBSEARCH_DATABASE_URL"] == f"sqlite:///{shell}"
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(config), "upgrade", "head"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert shell.exists() and not dotenv.exists()
    del env["JOBSEARCH_DATABASE_URL"]
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(config), "upgrade", "head"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert dotenv.exists() and not (tmp_path / "fallback.db").exists()
    import sqlite3
    for path in (explicit, shell, dotenv):
        connection = sqlite3.connect(path)
        try:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
        finally:
            connection.close()


def test_cli_create_view_partial_update_and_errors(database, tmp_path):
    url, factory = database
    with factory() as session:
        session.add(Applicant(id=40, full_name="Existing Fictional"))
        session.commit()
    env = {**os.environ, "JOBSEARCH_DATABASE_URL": url}
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "jobsearch.scripts.applicant_cli", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    payload = tmp_path / "input.json"
    payload.write_text(json.dumps({"full_name": "Fictional CLI", "remote_preference": " REMOTE "}))
    result = cli("create", "--input", str(payload))
    assert result.returncode == 0, result.stderr
    applicant_id = result.stdout.strip().split("id=")[1]
    assert applicant_id != "1"
    result = cli("view", "--id", applicant_id)
    assert result.returncode == 0
    assert json.loads(result.stdout)["remote_preference"] == "remote"
    payload.write_text('{"skills": ["Python"]}')
    assert cli("update", "--id", applicant_id, "--input", str(payload)).returncode == 0
    assert json.loads(cli("view", "--id", applicant_id).stdout)["skills"] == ["Python"]
    for value in ('{', '[]', '{"full_name": ""}', '{"full_name": "Example", "id": 1}'):
        payload.write_text(value)
        result = cli("create", "--input", str(payload))
        assert result.returncode != 0 and "error:" in result.stderr
    payload.write_text('{"phone": 42}')
    assert cli("update", "--id", applicant_id, "--input", str(payload)).returncode != 0
    payload.write_text('{}')
    for args in (("view", "--id", "99999"), ("update", "--id", "99999", "--input", str(payload)), ("view",), ("update", "--input", str(payload)), ("view", "--id", "0")):
        assert cli(*args).returncode != 0


def test_ingestion_failure_after_jobs_queued(database, monkeypatch):
    from jobsearch.scripts.run_fixture_ingestion import run_fixture_ingestion
    url, factory = database
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", url)
    queued = []
    def fail_with_jobs(session, flush_context, instances):
        jobs = [obj for obj in session.new if isinstance(obj, Job)]
        if jobs:
            queued.extend(jobs)
            raise ValueError("failure after jobs queued")
    event.listen(Session, "before_flush", fail_with_jobs)
    try:
        with pytest.raises(ValueError, match="after jobs queued"):
            run_fixture_ingestion(ROOT / "data/jobs_fixture.json")
    finally:
        event.remove(Session, "before_flush", fail_with_jobs)
    assert len(queued) == 2
    with factory() as session:
        assert session.query(Job).count() == 0
        run = session.query(ProcessingRun).one()
        assert run.status == "failed" and run.jobs_new == 0
        assert run.error_message == "failure after jobs queued"
        assert run.completed_at is not None


@pytest.mark.parametrize("fixture,seen,initial,repeated", [
    ("jobs_fixture.json", 2, (2, 0, 0), (0, 2, 0)),
    ("jobs_fixture_with_duplicates.json", 3, (2, 1, 0), (0, 3, 0)),
    ("jobs_fixture_with_filtered.json", 3, (2, 0, 1), (0, 2, 1)),
    ("jobs_fixture_missing_source_id.json", 2, (0, 0, 2), (0, 0, 2)),
])
def test_documented_fixture_counts_and_last_seen(database, monkeypatch, fixture, seen, initial, repeated):
    from jobsearch.scripts.run_fixture_ingestion import run_fixture_ingestion
    url, factory = database
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", url)
    for expected in (initial, repeated):
        assert run_fixture_ingestion(ROOT / "data" / fixture) == expected[0]
        with factory() as session:
            run = session.query(ProcessingRun).order_by(ProcessingRun.id.desc()).first()
            assert run.records_seen == seen
            assert (run.jobs_new, run.jobs_deduplicated, run.records_invalid) == expected
            jobs = session.query(Job).all()
            if expected == repeated and jobs:
                assert all(job.last_seen_at > job.first_seen_at for job in jobs)


@pytest.mark.parametrize("value,expected", [("remote", True), ("REMOTE", True), ("hybrid", False), ("onsite", False), (None, False), ("", False)])
def test_remote_preference_evaluation(value, expected):
    from jobsearch.evaluation.rules import evaluate
    result = evaluate({"remote_preference": "remote"}, {"remote_type": value})
    assert (result.decision == "keep") is expected
    assert result.decision == ("keep" if expected else "review" if not value else "reject")


def test_private_inputs_ignored_and_sample_available():
    result = subprocess.run(["git", "check-ignore", "data/private/profile.json", "data/backups/snapshot.db"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0
    assert len(result.stdout.splitlines()) == 2
    result = subprocess.run(["git", "check-ignore", "data/applicant_sample.json"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads((ROOT / "data/applicant_sample.json").read_text())["full_name"]
