from copy import deepcopy
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from jobsearch.evaluation import tier_rules
from jobsearch.models import Applicant, Job, JobEvaluation, ProcessingRun, RequestAttempt
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.evaluation_cli import main
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.storage.policy_repository import PolicyRepository


@pytest.fixture
def context():
    bundle = json.loads(Path('data/search_policy_sample.json').read_text())
    bundle.pop('applicant')
    bundle.update(applicant_id=1, revision=1)
    # Preserve coverage of the historical provisional-routing behavior.
    return dict(search_policy=bundle, applicant={}, rules_version='tier-policy-v2',
                job=dict(title='Example senior role', remote_type='remote', employment_type='full_time'))


def reason(result, check):
    return next(r for r in result.reasons if r['check'] == check)


@pytest.mark.parametrize('tier', list('ABCD'))
def test_routes_each_tier_without_inventing_fit(context, tier):
    strategy = context['search_policy']['strategies'][ord(tier) - ord('A')]
    context['job']['title'] = 'Lead ' + strategy['definition']['roles'][0].upper() + ' II'
    result = tier_rules.evaluate(context)
    assert result.tier == tier and result.decision == 'review'
    assert result.tailoring_level == strategy['definition']['tailoring']
    for dimension in ('hireability', 'career_value', 'income_value', 'application_friction'):
        assert reason(result, dimension)['outcome'] == 'review'


def test_overlap_disabled_and_no_fallback(context):
    strategies = context['search_policy']['strategies']
    strategies[1]['definition']['roles'] = strategies[0]['definition']['roles'][:]
    result = tier_rules.evaluate(context)
    assert result.tier == 'A'
    assert [c['tier'] for c in reason(result, 'tier_assignment')['candidates']] == ['A', 'B']
    strategies[0]['enabled'] = False
    assert tier_rules.evaluate(context).tier == 'B'
    strategies[1]['enabled'] = False
    result = tier_rules.evaluate(context)
    assert result.tier is None and result.tailoring_level is None and result.decision == 'review'
    for strategy in strategies:
        strategy['enabled'] = False
    assert tier_rules.evaluate(context).decision == 'review'


@pytest.mark.parametrize('title', [None, '', 'Example senior roles', 'Unlisted interesting opportunity'])
def test_unmatched_title_never_rejects(context, title):
    context['job']['title'] = title
    result = tier_rules.evaluate(context)
    assert result.decision == 'review' and result.tier is None


@pytest.mark.parametrize('employment,expected', [
    ('c2c', 'reject'), ('w2_contract', 'keep'), ('contract', 'review'),
    ('consulting', 'review'), ('part_time', 'keep'), (None, 'review'), ('unfamiliar', 'review')])
def test_employment_certainty(context, employment, expected):
    context['job']['employment_type'] = employment
    result = tier_rules.evaluate(context)
    assert reason(result, 'employment')['outcome'] == expected
    assert result.decision == ('reject' if expected == 'reject' else 'review')
    assert len(result.reasons) >= 10  # rejection does not skip other checks


def test_known_constraint_failure_and_or_alternatives(context):
    policy = context['search_policy']['policy']
    context['job']['remote_type'] = 'hybrid'
    assert reason(tier_rules.evaluate(context), 'work_arrangement')['outcome'] == 'keep'
    policy['location']['alternatives'] = policy['location']['alternatives'][:1]
    assert tier_rules.evaluate(context).decision == 'reject'
    context['job']['remote_type'] = None
    assert tier_rules.evaluate(context).decision == 'review'
    policy['employment_types'] = ['part_time']
    assert tier_rules.evaluate(context).decision == 'reject'


@pytest.mark.parametrize('description', [None, 'No clearance required. Certification preferred.',
                                       'Active clearance required. Mandatory license required.'])
def test_prose_and_incomplete_credentials_require_review(context, description):
    context['job'].update(description=description, location='Example metro area')
    result = tier_rules.evaluate(context)
    assert result.decision == 'review'
    for check in ('geography', 'active_clearance_required', 'known_missing_mandatory_credentials', 'eligibility'):
        assert reason(result, check)['outcome'] == 'review'


def test_compensation_and_friction_remain_independent(context):
    context['job'].update(salary_min=1, salary_max=2, salary_currency='USD', salary_period='hourly')
    context['search_policy']['strategies'][0]['definition']['max_application_minutes'] = 5
    result = tier_rules.evaluate(context)
    assert result.decision == 'review'
    assert 'available' in reason(result, 'income_value')['message']
    assert reason(result, 'application_friction')['max_application_minutes'] == 5
    context['job']['salary_min'] = float('inf')
    assert 'incomplete' in reason(tier_rules.evaluate(context), 'income_value')['message']


def test_history_replay_policy_versions_and_isolation(tmp_path, context, monkeypatch, capsys):
    url = f'sqlite:///{tmp_path / "tier.db"}'
    run_migrations(url)
    factory = build_session_factory(url)
    try:
        with factory() as session:
            applicant = Applicant(full_name='Fictional', skills=['Example skill'], minimum_salary=999999)
            job = JsonJobNormalizer.normalize(dict(source_job_id='one', **context['job']))
            session.add_all([applicant, job])
            session.flush()
            policies = PolicyRepository(session)
            bundle = context['search_policy']
            policies.save(applicant.id, bundle['policy'], bundle['strategies'])
            repo = EvaluationRepository(session)
            rows, counts = repo.evaluate_jobs(applicant.id)
            first = rows[0]
            saved = deepcopy(first.input_context)
            assert counts['review'] == 1 and first.tier is None and first.queue_state == 'unresolved'
            assert next(r for r in first.reasons if r['check'] == 'tier_assignment')['candidates'][0]['tier'] == 'A'
            assert repo.evaluate_jobs(applicant.id)[1]['unchanged'] == 1
            # An unrelated legacy global salary floor is deliberately not used.
            assert 'preferences' not in saved
            assert tier_rules.evaluate(saved).reasons == first.reasons
            revision = policies.view(applicant.id)
            revision['strategies'][0]['enabled'] = False
            policies.save(applicant.id, revision['policy'], revision['strategies'], expected_revision=1)
            second = repo.evaluate_jobs(applicant.id)[0][0]
            assert second.id != first.id and second.tier is None
            assert second.input_context['search_policy']['revision'] == 2
            job.description = 'New requirement text'
            third = repo.evaluate_jobs(applicant.id)[0][0]
            assert third.id != second.id
            applicant.skills.append('Additional reported skill')
            fourth = repo.evaluate_jobs(applicant.id)[0][0]
            assert fourth.id != third.id
            monkeypatch.setattr(tier_rules, 'RULES_VERSION', 'tier-policy-test-v2')
            fifth = repo.evaluate_jobs(applicant.id)[0][0]
            assert fifth.id != fourth.id
            assert first.input_context == saved
            assert tier_rules.evaluate(saved).reasons == first.reasons
            assert all(getattr(first, field) is None for field in (
                'hireability_score', 'career_value_score', 'income_value_score',
                'application_friction_score', 'model_name', 'estimated_ai_cost'))
            assert job.status == 'new'
            assert session.query(Applicant).count() == 1
            assert session.query(ProcessingRun).count() == session.query(RequestAttempt).count() == 0
            assert session.connection().exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
            assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
            session.commit()
        assert main(['--database-url', url, 'list', '--applicant-id', '1']) == 0
        output = capsys.readouterr().out
        assert 'policy-revision=1 provisional-tier=unassigned tailoring=unassigned' in output
        assert 'policy-revision=2 provisional-tier=unassigned' in output
        with factory() as session:
            assert session.query(JobEvaluation).count() == 5
    finally:
        factory.kw['bind'].dispose()


def test_batch_failure_rolls_back(tmp_path, context, monkeypatch):
    url = f'sqlite:///{tmp_path / "rollback.db"}'
    run_migrations(url)
    factory = build_session_factory(url)
    try:
        with factory() as session:
            session.add(Applicant(id=1, full_name='Fictional'))
            session.flush()
            bundle = context['search_policy']
            PolicyRepository(session).save(1, bundle['policy'], bundle['strategies'])
            session.add_all([JsonJobNormalizer.normalize(dict(source_job_id=str(i), **context['job'])) for i in range(2)])
            session.commit()
        original = tier_rules.evaluate
        calls = []
        def fail_second(snapshot):
            calls.append(snapshot)
            if len(calls) == 2:
                raise ValueError('Deliberate test failure')
            return original(snapshot)
        monkeypatch.setattr(tier_rules, 'evaluate', fail_second)
        with pytest.raises(SystemExit, match='Deliberate test failure'):
            main(['--database-url', url, 'evaluate', '--applicant-id', '1'])
        with factory() as session:
            assert session.scalars(select(JobEvaluation)).all() == []
            assert session.query(Job).count() == 2
    finally:
        factory.kw['bind'].dispose()
