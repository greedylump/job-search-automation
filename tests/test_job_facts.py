from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from jobsearch.evaluation import job_facts, tier_rules
from jobsearch.models import Applicant, Job, JobEvaluation, ProcessingRun
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.init_db import run_migrations
from jobsearch.scripts.job_facts_cli import main
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.storage.policy_repository import PolicyRepository


def instant(value):
    return job_facts.parse_as_of(value)


def job(description='', **changes):
    return dict(description=description, ats_type='usajobs', employment_type='Full Time', **changes)


@pytest.mark.parametrize('raw,expected', [
    ('Full Time', 'full_time'), (' FULL-TIME ', 'full_time'), ('Part Time', 'part_time'),
    ('W-2 contract', 'w2_contract'), ('corp-to-corp', 'c2c'), ('contract', 'contract'),
    ('Permanent', None), ('freelance', None), ('20 to 40 hours', None), (None, None)])
def test_employment_aliases_retain_source(raw, expected):
    inputs = {'employment_type': raw}
    result = job_facts.extract(inputs)
    assert result['employment']['value'] == expected
    assert inputs == {'employment_type': raw}
    assert result['employment']['evidence'] == ([] if raw is None else [
        dict(field='employment_type', start=0, end=len(raw), text=raw)])


@pytest.mark.parametrize('as_of,status', [
    ('2026-09-20T16:59:59Z', 'before_reported_deadline'),
    ('2026-09-20T17:00:00Z', 'past_reported_deadline'),
    ('2026-09-21T00:00:00+01:00', 'past_reported_deadline')])
def test_offset_deadline_boundary(as_of, status):
    result = job_facts.extract(job('Application closes: 2026-09-20T12:00:00-05:00'), instant(as_of))
    assert result['availability']['status'] == status
    assert result['availability']['precision'] == 'offset_datetime'


@pytest.mark.parametrize('raw,as_of,status', [
    ('2026-09-20', '2026-09-20T12:00:00Z', 'deadline_uncertain'),
    ('2026-09-20', '2026-09-21T23:59:59Z', 'deadline_uncertain'),
    ('2026-09-20', '2026-09-22T00:00:00Z', 'past_reported_deadline'),
    ('2026-09-20T23:59:59.9970', '2026-09-21T12:00:00Z', 'deadline_uncertain'),
    ('2026-09-20T23:59:59.9970', '2026-09-22T00:00:00Z', 'past_reported_deadline'),
    ('2026-09-25', '2026-09-20T12:00:00Z', 'before_reported_deadline'),
    ('2026-02-30', '2026-09-20T12:00:00Z', 'unknown'),
    ('9999-12-31', '2026-09-20T12:00:00Z', 'unknown'),
    ('until filled', '2026-09-20T12:00:00Z', 'unknown')])
def test_unknown_timezone_and_invalid_dates(raw, as_of, status):
    result = job_facts.extract(job('Application closes: ' + raw), instant(as_of))
    assert result['availability']['status'] == status


def test_deadline_provenance_conflicts_and_no_clock():
    text = 'Summary: Example\n\nApplication closes: 2026-09-20T00:00:00Z'
    inputs = job(text)
    assert job_facts.extract(inputs)['availability']['status'] == 'unknown'
    facts = job_facts.extract(inputs, instant('2026-09-21T00:00:00Z'))
    proof = facts['availability']['evidence'][0]
    assert text[proof['start']:proof['end']] == proof['text']
    inputs['description'] += '\nApplication closes: 2027-09-20'
    assert job_facts.extract(inputs, instant('2026-09-21T00:00:00Z'))['availability']['status'] == 'unknown'
    inputs.update(description=text, ats_type='other')
    assert job_facts.extract(inputs, instant('2026-09-21T00:00:00Z'))['availability']['status'] == 'unknown'
    with pytest.raises(ValueError, match='timezone-aware'):
        job_facts.extract(inputs, datetime(2026, 9, 20))
    with pytest.raises(ValueError, match='UTC offset'):
        instant('2026-09-20T00:00:00')


@pytest.mark.parametrize('sentence,requirement', [
    ('This position requires a Secret clearance.', 'required'),
    ('This position requires a Top Secret security clearance.', 'required'),
    ('Must obtain and maintain a Secret clearance.', 'required'),
    ('You must be able to obtain and maintain a Secret clearance.', 'required'),
    ('Must currently possess an active Secret clearance.', 'active_required'),
    ('You must hold an active Top Secret clearance.', 'active_required')])
def test_narrow_requirements_and_exact_evidence(sentence, requirement):
    text = 'Summary: Other text.\n\nRequirements: ' + sentence + '\n\nEducation: Other text.'
    facts = job_facts.extract(job(text))
    assert len(facts['requirements']) == 1
    fact = facts['requirements'][0]
    assert fact['requirement'] == requirement
    proof = fact['evidence']
    assert text[proof['start']:proof['end']] == proof['text'] == sentence


@pytest.mark.parametrize('text', [
    'Requirements: No Secret clearance required.',
    'Requirements: This position does not require a Secret clearance.',
    'Requirements: This position may require a Secret clearance.',
    'Requirements: If selected for another role, this position requires a Secret clearance.',
    'Requirements: This position requires a Secret clearance or equivalent experience.',
    'Requirements: This position requires a Public Trust clearance.',
    'Summary: This position requires a Secret clearance.',
    'Qualifications: This position requires a Secret clearance.',
    'Requirements: This position requires a Secret clearance. No clearance is required.',
    'Requirements: This position requires a Secret clearance. Clearance may be waived.',
    'Requirements: This position requires a Secret clearance. This requirement may be waived.',
    'Requirements: For example. This position requires a Secret clearance.',
    'Requirements: Other details.\n\nEducation: This position requires a Secret clearance.',
    'Requirements: This position requires a Secret clearance.\n\nRequirements: No clearance required.'
])
def test_ambiguous_requirements_do_not_become_facts(text):
    assert job_facts.extract(job(text))['requirements'] == []


def context(inputs):
    bundle = json.loads(Path('data/search_policy_sample.json').read_text())
    bundle.pop('applicant')
    return dict(search_policy=bundle, job=inputs, rules_version=tier_rules.RULES_VERSION,
                facts_as_of='2026-09-20T12:00:00+00:00')


def test_policy_clearance_scope_and_v1_replay():
    inputs = context(job('Requirements: This position requires a Secret clearance.'))
    result = tier_rules.evaluate(inputs)
    checks = {r['check']: r for r in result.reasons}
    assert result.decision == 'reject'
    assert checks['clearance_core_requirement']['outcome'] == 'reject'
    assert checks['active_clearance_required']['outcome'] == 'review'
    assert checks['employment']['outcome'] == 'keep'
    inputs['search_policy']['policy']['exclusions'] = ['active_clearance_required']
    assert tier_rules.evaluate(inputs).decision == 'review'
    inputs['job']['description'] = 'Requirements: Must hold an active Secret clearance.'
    assert tier_rules.evaluate(inputs).decision == 'reject'
    inputs['rules_version'] = 'tier-policy-v1'
    assert tier_rules.evaluate(inputs) == tier_rules.evaluate_v1(inputs)
    assert tier_rules.evaluate(inputs).decision == 'review'


def test_availability_history_and_cli_readonly(tmp_path, capsys):
    path = tmp_path / 'facts.db'
    url = f'sqlite:///{path}'
    run_migrations(url)
    factory = build_session_factory(url)
    try:
        with factory() as session:
            session.add(Applicant(id=1, full_name='Fictional'))
            session.flush()
            bundle = context({})['search_policy']
            PolicyRepository(session).save(1, bundle['policy'], bundle['strategies'])
            session.add(JsonJobNormalizer.normalize(dict(source_job_id='one', title='Example senior role',
                **job('Application closes: 2026-09-20T12:00:00Z'))))
            session.commit()
            repo = EvaluationRepository(session)
            first = repo.evaluate_jobs(1, as_of=instant('2026-09-20T10:00:00Z'))[0][0]
            original = deepcopy(first.input_context)
            assert first.decision == 'review'
            assert repo.evaluate_jobs(1, as_of=instant('2026-09-20T11:00:00Z'))[1]['unchanged'] == 1
            second = repo.evaluate_jobs(1, as_of=instant('2026-09-20T12:00:00Z'))[0][0]
            assert second.id != first.id and second.decision == 'reject'
            assert repo.evaluate_jobs(1, as_of=instant('2026-09-21T00:00:00Z'))[1]['unchanged'] == 1
            assert first.input_context == original
            assert tier_rules.evaluate(original).reasons == first.reasons
            assert session.query(Job).one().status == 'new'
            assert session.query(ProcessingRun).count() == 0
            assert session.connection().exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
            assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
            session.commit()
        before = path.read_bytes()
        main(['--database', str(path), '--as-of', '2026-09-20T13:00:00Z', '--summary-only'])
        result = json.loads(capsys.readouterr().out)
        assert result['availability'] == {'past_reported_deadline': 1}
        assert result['employment'] == {'full_time': 1}
        assert before == path.read_bytes()
        with factory() as session:
            assert session.query(JobEvaluation).count() == 2
    finally:
        factory.kw['bind'].dispose()


def test_cli_missing_file_does_not_create_database(tmp_path):
    import sqlite3
    path = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        main(['--database', str(path)])
    assert not path.exists()
