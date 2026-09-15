from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from jobsearch.collectors import remotive_collector as collector_module
from jobsearch.collectors.remotive_collector import RemotiveCollector, API_URL
from jobsearch.models import Applicant, Job, ProcessingRun, JobSource
from jobsearch.normalization.remotive_normalizer import RemotiveJobNormalizer
from jobsearch.scripts.run_remotive_ingestion import main, run_remotive_ingestion
from jobsearch.scripts.run_fixture_ingestion import run_fixture_ingestion
from jobsearch.storage.database import get_session, close_session

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "remotive_sample.json"


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Tests must never call the live API")
    monkeypatch.setattr(collector_module, "urlopen", unexpected)


def serve(monkeypatch, raw):
    requests = []
    def response(request, timeout):
        requests.append((request, timeout))
        return BytesIO(raw)
    monkeypatch.setattr(collector_module, "urlopen", response)
    return requests


def test_skip_preserves_jobs_and_request_state(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    requests = serve(monkeypatch, SAMPLE.read_bytes())
    first = run_remotive_ingestion(database_url=url)
    session = get_session(url)
    try:
        before = [(job.id, job.last_seen_at) for job in session.query(Job).order_by(Job.id)]
        state = session.get(JobSource, "remotive")
        assert state.collection_strategy == "full_feed" and state.response_retention == "none"
        assert state.request_attempts == 1 and state.last_http_status == 200
        assert state.last_success_at is not None
        allowed = state.next_allowed_at
    finally:
        close_session(session)
    second = run_remotive_ingestion(database_url=url)
    assert first.jobs_new == 2 and second.status == "skipped"
    assert second.records_seen == second.jobs_new == second.jobs_deduplicated == 0
    assert second.ai_cost == 0 and second.jobs_scored == 0
    assert second.skip_reason and second.next_eligible_at == allowed
    assert len(requests) == 1
    assert requests[0][0].full_url == API_URL and requests[0][1] == 30
    session = get_session(url)
    try:
        assert [(job.id, job.last_seen_at) for job in session.query(Job).order_by(Job.id)] == before
        assert session.get(JobSource, "remotive").request_attempts == 1
    finally:
        close_session(session)


def test_normalization_preserves_source_fields_without_salary_guesses():
    payload = json.loads(SAMPLE.read_text())["jobs"][0]
    job = RemotiveJobNormalizer.normalize(payload)
    assert (job.source, job.source_job_id) == ("remotive", "101")
    assert job.title == "Python & Data Engineer"
    assert job.company == "Fictional Example Co"
    assert job.location == "USA, Canada" and job.remote_type == "remote"
    assert job.employment_type == "full_time"
    assert job.job_url == payload["url"] and job.apply_url is None
    assert job.posted_at.isoformat() == "2026-09-01T10:00:00"
    assert "Salary (source text): $100,000 - $140,000" in job.description
    assert "SQL & testing" in job.description and "<p>" not in job.description
    assert job.salary_min is job.salary_max is job.salary_currency is job.salary_period is None


@pytest.mark.parametrize("identifier", [None, True, {}, [], 0, -1, " "])
def test_unusable_ids_remain_invalid(identifier):
    assert RemotiveJobNormalizer.normalize({"id": identifier}).source_job_id is None


def test_malformed_optional_fields_do_not_break_normalization():
    job = RemotiveJobNormalizer.normalize({"id": " a ", "title": 42, "company_name": [],
        "url": "javascript:alert(1)", "publication_date": "bad", "salary": {},
        "description": "<script>hidden()</script><p>Visible</p>"})
    assert job.source_job_id == "a"
    assert job.title is job.company is job.job_url is job.posted_at is None
    assert job.description == "Visible"


def test_live_pipeline_metrics_replay_and_source_isolation(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", url)
    payload = json.loads(SAMPLE.read_text())
    payload["jobs"] += [None, {}, {"id": 103, "title": 42}, payload["jobs"][0]]
    requests = serve(monkeypatch, json.dumps(payload).encode())
    snapshot = tmp_path / "snapshot.json"
    first = run_remotive_ingestion(snapshot_path=snapshot)
    second = run_remotive_ingestion(replay_path=snapshot)
    assert (first.records_seen, first.jobs_new, first.jobs_deduplicated, first.records_invalid) == (6, 2, 1, 3)
    assert (second.records_seen, second.jobs_new, second.jobs_deduplicated, second.records_invalid) == (6, 0, 3, 3)
    assert len(requests) == 1
    for run in (first, second):
        assert run.invalid_reason_counts == {"non_object": 1, "missing_source_id": 1, "invalid_title": 1}
        assert run.status == "completed" and run.started_at <= run.completed_at
        assert run.jobs_scored == 0 and run.ai_cost == 0
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps([{"id": 101, "title": "Different source"}]))
    assert run_fixture_ingestion(fixture) == 1
    session = get_session(url)
    try:
        assert session.query(Job).count() == 3
        assert session.query(ProcessingRun).count() == 3
        assert {job.source for job in session.query(Job)} == {"remotive", "fixture_json"}
    finally:
        close_session(session)


@pytest.mark.parametrize("failure", [
    HTTPError(API_URL, 429, "Too many requests", {}, None),
    HTTPError(API_URL, 503, "Unavailable", {}, None),
    URLError("connection failed"), TimeoutError(),
])
def test_network_errors_are_not_retried_and_run_is_failed(tmp_path, monkeypatch, failure):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise failure
    monkeypatch.setattr(collector_module, "urlopen", fail)
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    with pytest.raises(RuntimeError):
        run_remotive_ingestion(database_url=url)
    assert len(calls) == 1 and not (tmp_path / "cache.json").exists()
    assert run_remotive_ingestion(database_url=url).status == "skipped"
    assert len(calls) == 1
    session = get_session(url)
    try:
        run = session.query(ProcessingRun).order_by(ProcessingRun.id).first()
        assert run.status == "failed" and run.error_message
        assert run.records_seen == run.jobs_new == 0
        assert session.query(Job).count() == 0
    finally:
        close_session(session)


@pytest.mark.parametrize("raw", [b"<html>unavailable</html>", b"[]", b'{"jobs":null}'])
def test_invalid_response_consumes_request_slot(tmp_path, monkeypatch, raw):
    requests = serve(monkeypatch, raw)
    url = f"sqlite:///{tmp_path / 'invalid.db'}"
    with pytest.raises(ValueError):
        run_remotive_ingestion(database_url=url)
    assert run_remotive_ingestion(database_url=url).status == "skipped"
    assert len(requests) == 1


def test_size_bound_and_empty_response(tmp_path, monkeypatch):
    monkeypatch.setattr(collector_module, "MAX_RESPONSE_BYTES", 20)
    serve(monkeypatch, b"x" * 21)
    with pytest.raises(ValueError, match="limit"):
        run_remotive_ingestion(database_url=f"sqlite:///{tmp_path / 'big.db'}")
    serve(monkeypatch, b'{"jobs":[]}')
    run = run_remotive_ingestion(database_url=f"sqlite:///{tmp_path / 'empty.db'}")
    assert run.status == "completed" and run.records_seen == run.jobs_new == 0


def test_cli_display_filter_does_not_filter_ingestion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBSEARCH_DATA_DIR", str(tmp_path))
    serve(monkeypatch, SAMPLE.read_bytes())
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    assert main(["--database-url", url, "--title", "python", "--show", "1"]) == 0
    output = capsys.readouterr().out
    assert "Records seen=2 new=2" in output
    assert "Python & Data Engineer" in output and "Backend Developer" not in output
    assert "Source: Remotive" in output and "https://remotive.com/" in output
    assert main(["--database-url", url, "--title", "%"]) == 0
    assert "No stored titles match" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main(["--show", "-1"])
    assert exc.value.code != 0


def test_insertion_failure_keeps_source_run_and_explicit_snapshot(tmp_path, monkeypatch):
    serve(monkeypatch, SAMPLE.read_bytes())
    url = f"sqlite:///{tmp_path / 'failure.db'}"
    snapshot = tmp_path / "snapshot.json"
    def fail(session, flush_context, instances):
        if any(isinstance(obj, Job) for obj in session.new):
            raise ValueError("insertion failed")
    event.listen(Session, "before_flush", fail)
    try:
        with pytest.raises(ValueError, match="insertion failed"):
            run_remotive_ingestion(database_url=url, snapshot_path=snapshot)
    finally:
        event.remove(Session, "before_flush", fail)
    session = get_session(url)
    try:
        run = session.query(ProcessingRun).one()
        assert run.source == "remotive" and run.status == "failed" and run.jobs_new == 0
        assert session.query(Job).count() == 0 and snapshot.exists()
    finally:
        close_session(session)


def test_remotive_evaluation_preserves_attribution_and_requires_salary_review(tmp_path, monkeypatch, capsys):
    from jobsearch.scripts.evaluation_cli import main as evaluate_main
    url = f"sqlite:///{tmp_path / 'evaluation.db'}"
    monkeypatch.setenv("JOBSEARCH_DATABASE_URL", url)
    serve(monkeypatch, SAMPLE.read_bytes())
    run_remotive_ingestion()
    session = get_session(url)
    try:
        applicant = Applicant(full_name="Fictional Evaluation", minimum_salary=100000,
                              salary_currency="USD", salary_period="annual", remote_preference="remote")
        session.add(applicant)
        session.commit()
        applicant_id = applicant.id
    finally:
        close_session(session)
    assert evaluate_main(["evaluate", "--applicant-id", str(applicant_id)]) == 0
    output = capsys.readouterr().out
    assert "review-needed=2" in output
    assert "Source: Remotive | https://remotive.com/" in output
