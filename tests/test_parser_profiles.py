from copy import deepcopy
import json
from pathlib import Path

import pytest

from jobsearch.evaluation import qualification as q, tier_rules
from jobsearch.evaluation.parser_profiles import load_profile, resolve_profile
from jobsearch.models import JobEvaluation
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.evaluation_cli import main
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.policy_repository import PolicyRepository
from jobsearch.storage.evaluation_repository import EvaluationRepository


def evidence(skill, years):
    return dict(schema_version=1, job_exclusions=[], skills=[dict(skill=skill,
        commercial_years_min=years, commercial_years_max=years, expertise=None,
        source='Fictional professional work history')])


@pytest.mark.parametrize('canonical,alias', [('accounts payable', 'A/P'), ('critical care', 'ICU')])
def test_same_engine_different_careers_and_applicants(canonical, alias):
    profile = load_profile('data/requirement_parser_accounting.json')
    profile['name'] = 'fictional-career'
    profile['aliases'] = {alias.lower(): canonical}
    description = f'Essential qualifications: Professional experience: {alias}: 3+ years Benefits: Other vacancies'
    parsed = q.extract_requirements({'description': description}, profile)
    assert parsed['complete']
    assert q.assess({}, evidence(canonical, 5), parsed)['status'] == 'supported'
    assert q.assess({}, evidence(canonical, 1), parsed)['status'] == 'mismatch'
    assert q.assess({}, evidence('unrelated work', 12), parsed)['status'] == 'unknown'
    assert not q.extract_requirements({'description': description})['complete']
    for proof in parsed['evidence']:
        assert description[proof['start']:proof['end']] == proof['text']
    profile['aliases'].clear()
    assert parsed['parser_profile']['aliases'] == {alias.lower(): canonical}


def test_custom_grammar_and_or_negation_and_incomplete_coverage():
    profile = load_profile('data/requirement_parser_accounting.json')
    profile['patterns']['years_clause'] = r'\s*([\w /]+?)\s+at least\s+(\d+)\s+years\s*'
    text = 'Essential qualifications: Professional experience: A/P at least 4 years OR bookkeeping at least 2 years'
    parsed = q.extract_requirements({'description': text}, profile)
    assert parsed['complete']
    assert q.assess({}, evidence('bookkeeping', 3), parsed)['status'] == 'supported'
    assert q.assess({}, evidence('accounts payable', 1), parsed)['status'] == 'unknown'
    waived = q.extract_requirements({'description': text + ' Equivalent experience is accepted.'}, profile)
    assert not waived['complete'] and q.assess({}, evidence('accounts payable', 1), waived)['status'] == 'unknown'
    negated = q.extract_requirements({'description': 'Essential qualifications: No Professional experience: A/P at least 4 years'}, profile)
    assert q.assess({}, evidence('accounts payable', 0), negated)['status'] == 'unknown'


@pytest.mark.parametrize('mutation', ['schema', 'missing', 'regex', 'capture', 'empty', 'cycle', 'chain', 'revision'])
def test_invalid_profiles_fail_explicitly(mutation):
    profile = resolve_profile()
    if mutation == 'schema': profile['schema_version'] = 2
    if mutation == 'missing': del profile['patterns']['years_clause']
    if mutation == 'regex': profile['patterns']['years_clause'] = '['
    if mutation == 'capture': profile['patterns']['years_clause'] = r'years (\d+)'
    if mutation == 'empty': profile['patterns']['section_heading'] = '.*'
    if mutation == 'cycle': profile['aliases'] = {'a': 'b', 'b': 'a'}
    if mutation == 'chain': profile['aliases'] = {'a': 'b', 'b': 'c'}
    if mutation == 'revision': profile['revision'] = True
    with pytest.raises(ValueError): resolve_profile(profile)


def test_frozen_default_compatibility():
    profile = load_profile('data/requirement_parser_software.json')
    assert profile == resolve_profile()
    profile['aliases'].clear()
    assert q.skill_key('React.js') == 'react'
    assert q.skill_key('React.js', profile) == 'react.js'


def test_profile_history_and_cli(tmp_path, capsys):
    url = f'sqlite:///{tmp_path / "profiles.db"}'
    run_migrations(url)
    factory = build_session_factory(url)
    profile = load_profile('data/requirement_parser_accounting.json')
    path = tmp_path / 'parser.json'
    path.write_text(json.dumps(profile))
    try:
        with factory() as session:
            person = ApplicantRepository(session).create_from_payload(dict(full_name='Fictional accountant', experience_evidence=evidence('accounts payable', 1)))
            bundle = json.loads(Path('data/search_policy_sample.json').read_text())
            PolicyRepository(session).save(person.id, bundle['policy'], bundle['strategies'])
            session.add(JsonJobNormalizer.normalize(dict(source_job_id='one', title='Accounts assistant',
                description='Essential qualifications: Professional experience: A/P: 3+ years')))
            session.commit()
        main(['--database-url', url, 'evaluate', '--applicant-id', '1', '--parser-profile', str(path), '--show-all'])
        assert 'do_not_pursue' in capsys.readouterr().out
        with factory() as session:
            repo = EvaluationRepository(session)
            first = session.query(JobEvaluation).one()
            snapshot = deepcopy(first.input_context)
            assert repo.evaluate_jobs(1, parser_profile=profile)[1]['unchanged'] == 1
            profile['aliases'] = {}
            # Even without a revision bump, changed profile contents change history.
            second = repo.evaluate_jobs(1, parser_profile=profile)[0][0]
            assert second.id != first.id and second.queue_state == 'unresolved'
            assert first.input_context == snapshot
            assert tier_rules.evaluate(snapshot).reasons == first.reasons
            assert session.connection().exec_driver_sql('PRAGMA foreign_key_check').all() == []
            session.commit()
    finally:
        factory.kw['bind'].dispose()
