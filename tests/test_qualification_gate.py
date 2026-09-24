from copy import deepcopy
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from jobsearch.evaluation import qualification as q, tier_rules
from jobsearch.models import Applicant, JobEvaluation
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.evaluation_cli import main
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.storage.policy_repository import PolicyRepository


# Fictional mandatory experience with two alternatives; no applicant data.
DESCRIPTION = ('Requirements: Commercial experience: React.js: 3+ years, Node.js: 5+ years, and Next.js: 2+ years '
               'OR React.js: 5+ years, Node.js: 3+ years, and Next.js: 2+ years '
               'Expertise in AWS, TypeScript and AI-assisted coding is a must. Benefits: Other projects use Python.')


def skill(name, low=None, high=None, expertise=None):
    return dict(skill=name, commercial_years_min=low, commercial_years_max=high,
                expertise=expertise, source='Fictional applicant statement')


def evidence(*rows):
    return dict(schema_version=1, skills=list(rows), job_exclusions=[])


def qualified():
    return evidence(skill('React', 3, 3), skill('Node', 5, 5), skill('Next', 2, 2),
                    skill('AWS', expertise=True), skill('TypeScript', expertise=True),
                    skill('AI-assisted coding', expertise=True))


def requirements(text=DESCRIPTION):
    return q.extract_requirements({'description': text})


def test_and_or_structure_and_evidence():
    parsed = requirements()
    assert parsed['complete']
    alternatives = parsed['tree']['children'][0]
    assert alternatives['op'] == 'any' and len(alternatives['children']) == 2
    assert all(len(branch['children']) == 3 for branch in alternatives['children'])
    for proof in parsed['evidence']:
        assert DESCRIPTION[proof['start']:proof['end']] == proof['text']
    assert q.compare(parsed['tree'], qualified())['status'] == 'supported'
    second = qualified()
    second['skills'][0] = skill('React', 5, 5)
    second['skills'][1] = skill('Node', 3, 3)
    assert q.compare(parsed['tree'], second)['status'] == 'supported'


@pytest.mark.parametrize('rows,status', [
    ([], 'unknown'), ([skill('Node', 0, 0)], 'mismatch'),
    ([skill('Node', 1, None)], 'unknown'), ([skill('Next', None, 1)], 'mismatch'),
    ([skill('React', 3, 3), skill('Node', 3, 3), skill('Next', 2, 2)], 'mismatch')])
def test_missing_vs_known_bounds_and_no_or_branch_mixing(rows, status):
    assert q.compare(requirements()['tree'], evidence(*rows))['status'] == status


def test_projects_skills_list_and_unknown_expertise_do_not_substitute():
    applicant = evidence(skill('Node', 0, 0))
    assert q.compare(requirements()['tree'], applicant)['status'] == 'mismatch'
    missing_expertise = qualified()
    missing_expertise['skills'][-1]['expertise'] = None
    assert q.compare(requirements()['tree'], missing_expertise)['status'] == 'unknown'


@pytest.mark.parametrize('suffix', [
    ' Equivalent experience may substitute.', ' This requirement may be waived.',
    ' Unless an exception applies.', ' Requirements: Different role requirements.',
    ' These skills are preferred.', ' These skills are optional.'
])
def test_ambiguous_scope_does_not_reject(suffix):
    text = DESCRIPTION.split(' Benefits:')[0] + suffix
    assessment = q.assess({}, evidence(skill('Node', 0, 0)), requirements(text))
    assert assessment['status'] == 'unknown'


def test_partial_coverage_and_unrelated_advertising():
    text = DESCRIPTION.replace('Requirements:', 'Requirements: 5+ years of software development experience ', 1)
    parsed = requirements(text)
    assert not parsed['complete']
    assert q.assess({}, qualified(), parsed)['status'] == 'unknown'
    assert q.assess({}, evidence(skill('Node', 0, 0)), parsed)['status'] == 'mismatch'
    assert requirements('Benefits: Other roles require React.js: 3+ years')['tree']['children'] == []
    assert not requirements('Requirements: Commercial experience: React or Node: 3+ years')['complete']


@pytest.mark.parametrize('mutation', ['negative', 'nan', 'inverted', 'bool', 'duplicate', 'unknown', 'source'])
def test_evidence_validation(mutation):
    data = evidence(skill('React', 3, 4))
    if mutation == 'negative': data['skills'][0]['commercial_years_min'] = -1
    if mutation == 'nan': data['skills'][0]['commercial_years_min'] = float('nan')
    if mutation == 'inverted': data['skills'][0]['commercial_years_min'] = 5
    if mutation == 'bool': data['skills'][0]['commercial_years_min'] = True
    if mutation == 'duplicate': data['skills'].append(skill('React.js'))
    if mutation == 'unknown': data['unexpected'] = True
    if mutation == 'source': data['skills'][0]['source'] = ''
    with pytest.raises(ValueError): q.validate_evidence(data)


def test_queue_gate_distinguishes_plausibility_from_value_judgment():
    supported = {'status': 'supported'}
    assert q.queue_state(supported, [{'check': 'career_value', 'outcome': 'review'}]) == 'plausible'
    assert q.queue_state(supported, [{'check': 'geography', 'outcome': 'review'}]) == 'unresolved'
    assert q.queue_state({'status': 'unknown'}, []) == 'unresolved'
    assert q.queue_state({'status': 'mismatch'}, []) == 'do_not_pursue'
    assert q.queue_state(supported, [{'check': 'availability', 'outcome': 'reject'}]) == 'do_not_pursue'


@pytest.mark.parametrize('text', ['Requirements: No Commercial experience: Node: 5+ years',
                                 'Requirements: Not Expertise in Node is a must.'])
def test_negation_is_not_a_mandatory_mismatch(text):
    assert q.assess({}, evidence(skill('Node', 0, 0, False)), requirements(text))['status'] == 'unknown'


def test_tiers_do_not_rescue_mismatch_and_old_rules_replay():
    bundle = json.loads(Path('data/search_policy_sample.json').read_text())
    context = dict(job={'title': 'Example senior role', 'description': DESCRIPTION}, search_policy=bundle,
                   applicant={'experience_evidence': evidence(skill('Node', 0, 0))}, rules_version='tier-policy-v3')
    result = tier_rules.evaluate(context)
    assert result.queue_state == 'do_not_pursue' and result.tier is None and result.tailoring_level is None
    assert next(r for r in result.reasons if r['check'] == 'tier_assignment')['candidates']
    context['rules_version'] = 'tier-policy-v2'
    result = tier_rules.evaluate(context)
    assert result.queue_state is None and result.tier == 'A'
    assert result == tier_rules.evaluate_v2(context)


def test_explicit_job_exclusion_is_scoped_and_does_not_invent_years():
    data = evidence()
    data['job_exclusions'] = [dict(source='fixture', source_job_id='one', reason='Applicant explicitly declined this stack requirement.')]
    q.validate_evidence(data)
    assert q.assess(dict(source='fixture', source_job_id='one'), data, requirements())['status'] == 'mismatch'
    assert q.assess(dict(source='another', source_job_id='one'), data, requirements())['status'] == 'unknown'
    assert data['skills'] == []


def test_migration_profile_history_and_cli_holds(tmp_path, capsys):
    url = f'sqlite:///{tmp_path / "qualification.db"}'
    config = Config('alembic.ini')
    config.attributes['database_url_override'] = url
    command.upgrade(config, '20260918_17')
    run_migrations(url)
    factory = build_session_factory(url)
    try:
        with factory() as session:
            applicants = ApplicantRepository(session)
            applicant = applicants.create_from_payload({'full_name': 'Fictional', 'skills': ['React', 'Node']})
            bundle = json.loads(Path('data/search_policy_sample.json').read_text())
            PolicyRepository(session).save(applicant.id, bundle['policy'], bundle['strategies'])
            session.add(JsonJobNormalizer.normalize({'source_job_id': 'one', 'title': 'Example senior role', 'description': DESCRIPTION}))
            session.commit()
            repo = EvaluationRepository(session)
            first = repo.evaluate_jobs(applicant.id)[0][0]
            saved = deepcopy(first.input_context)
            assert first.queue_state == 'unresolved' and first.tier is None
            applicants.update_from_payload(applicant.id, {'experience_evidence': evidence(skill('Node', 0, 0))})
            second = repo.evaluate_jobs(applicant.id)[0][0]
            assert second.id != first.id and second.queue_state == 'do_not_pursue'
            assert first.input_context == saved
            assert tier_rules.evaluate(saved).queue_state == 'unresolved'
            assert repo.evaluate_jobs(applicant.id)[1]['unchanged'] == 1
            session.commit()
        main(['--database-url', url, 'evaluate', '--applicant-id', '1'])
        output = capsys.readouterr().out
        assert 'Example senior role' not in output and 'do_not_pursue' in output
        main(['--database-url', url, 'evaluate', '--applicant-id', '1', '--show-all'])
        assert 'Example senior role' in capsys.readouterr().out
        with pytest.raises(RuntimeError, match='populated'):
            command.downgrade(config, '20260918_17')
        with factory() as session:
            assert session.query(JobEvaluation).count() == 2
            assert session.connection().exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
            assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
    finally:
        factory.kw['bind'].dispose()
