import json
from copy import deepcopy
from pathlib import Path
import pytest

from jobsearch.evaluation.role_signals import evaluate_signals
from jobsearch.evaluation.qualification import extract_requirements, assess
from jobsearch.evaluation.parser_profiles import resolve_profile
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.policy_repository import PolicyRepository
from jobsearch.scripts.init_db import run_migrations
from jobsearch.scripts.cross_career_report import build_report
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.evaluation.job_facts import parse_as_of
from jobsearch.evaluation import tier_rules
from jobsearch.models import JobEvaluation
from jobsearch.storage.evaluation_repository import EvaluationRepository


def profile():
    return json.loads(Path('data/requirement_parser_cross_career.json').read_text())


def accountant():
    return json.loads(Path('data/accounting_applicant_sample.json').read_text())


def developer():
    payload=accountant()
    payload['full_name']='SYNTHETIC TEST ONLY - Software Applicant'
    for row in payload['experience_evidence']['skills']:
        technical=row['skill'] in {'software development','C#','React'}
        row.update(state='established' if technical else 'none',commercial=technical,
                   approximate_years=6 if technical else None,expertise=None)
    return payload


def test_two_profiles_two_career_families_have_distinct_signals():
    p=profile()
    a=accountant()['experience_evidence']; d=developer()['experience_evidence']
    for title,yes,no in [('Accountant',a,d),('Software Developer',d,a)]:
        assert evaluate_signals({'title':title},yes,p)['supported']
        assert not evaluate_signals({'title':title},no,p)['supported']
    # Advertisements for other roles in descriptions must not create hits.
    assert not evaluate_signals({'title':'Accountant','description':'Other roles: Software Developer'},d,p)['supported']


def test_matching_title_cannot_override_explicit_stack_mismatch():
    d=developer()['experience_evidence']
    target=dict(title='Software Developer',description='Requirements: Commercial experience: accounting: 5+ years')
    assert evaluate_signals(target,d,profile())['supported']
    assert assess(target,d,extract_requirements(target,profile()))['status']=='mismatch'


def test_profiles_and_jobs_read_from_database(tmp_path):
    url=f'sqlite:///{tmp_path / "matrix.db"}'
    run_migrations(url); factory=build_session_factory(url)
    try:
        with factory() as session:
            ids=[]
            for payload in [developer(),accountant()]:
                person=ApplicantRepository(session).create_from_payload(payload); ids.append(person.id)
                bundle=json.loads(Path('data/search_policy_sample.json').read_text())
                PolicyRepository(session).save(person.id,bundle['policy'],bundle['strategies'])
            for key,title,skill in [('dev','Software Developer','C#'),('acct','Accountant','accounting')]:
                session.add(JsonJobNormalizer.normalize(dict(source_job_id=key,title=title,
                    description=f'Requirements: Commercial experience: {skill}: 3+ years')))
            session.commit()
        with factory() as session:
            report=build_report(session,ids,profile(),parse_as_of('2026-09-21T12:00:00Z'))
            for person in report['profiles']:
                records=person['records']
                assert sum(r['role_relevance'] for r in records)==1
                assert sorted(r['qualification'] for r in records)==['mismatch','supported']
                assert all(r['queue_state']!='plausible' for r in records) # eligibility unresolved
            session.commit()
        with factory() as session:
            repo = EvaluationRepository(session)
            original = repo.evaluate_jobs(ids[0], parser_profile=profile())[0][0]
            snapshot = deepcopy(original.input_context)
            payload = developer()['experience_evidence']
            payload['skills'][-1]['recency'] = 'Fictional updated evidence'
            ApplicantRepository(session).update_from_payload(ids[0], {'experience_evidence': payload})
            session.flush()
            changed = repo.evaluate_jobs(ids[0], parser_profile=profile())[0][0]
            assert changed.id != original.id
            assert original.input_context == snapshot
            assert tier_rules.evaluate(snapshot).reasons == original.reasons
            assert repo.evaluate_jobs(ids[0], parser_profile=profile())[1]['unchanged'] == 2
    finally: factory.kw['bind'].dispose()


@pytest.mark.parametrize('pattern', ['(', '(accountant)', '.*'])
def test_invalid_capability_patterns_are_rejected(pattern):
    p = profile()
    p['capability_signals'][0]['title_pattern'] = pattern
    with pytest.raises(ValueError):
        resolve_profile(p)
