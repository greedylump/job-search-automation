import json
from copy import deepcopy
from pathlib import Path

import pytest

from jobsearch.evaluation.qualification import compare, assess, extract_requirements, validate_evidence
from jobsearch.evaluation.parser_profiles import load_profile, resolve_profile
from jobsearch.evaluation import tier_rules
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.storage.policy_repository import PolicyRepository
from jobsearch.storage.database import build_session_factory
from jobsearch.scripts.init_db import run_migrations
from jobsearch.normalization.json_normalizer import JsonJobNormalizer


def payload():
    return json.loads(Path('data/accounting_work_sample.json').read_text(encoding='utf-8'))


def evidence():
    return payload()['experience_evidence']


def profile():
    return load_profile('data/requirement_parser_specialized.json')


def requirement():
    return dict(op='specialized_experience', activities=['financial_data_analysis',
        'accounting_problem_resolution','automated_financial_systems'], minimum_months=12,
        grade_system='GS',grade='07')


def description():
    return ('Qualifications: Specialized Experience, GS-09: One year of specialized experience which includes '
        'experience analyzing financial data in order to solve accounting problems using an automated financial system. '
        'This definition of specialized experience is typical of work performed at the second lower grade/level '
        'position in the federal service (GS-07). OR Education: An unsupported education alternative.')


def test_complete_branch_preserves_duties_duration_and_required_prior_grade():
    job=dict(description=description(),ats_type='usajobs')
    parsed=extract_requirements(job,profile())
    path=parsed['path_analysis']['paths'][0]
    assert path['grade']=='09'
    node=path['tree']['children'][0]
    assert node['op']=='specialized_experience' and node['grade']=='07'
    assert node['minimum_months']==12
    span=node['evidence']
    assert job['description'][span['start']:span['end']]==span['text']
    result=assess(job,evidence(),parsed)
    assert result['path_assessments'][0]['comparison']['status']=='supported'
    assert result['status']=='unknown' # local grade path is not full qualification


@pytest.mark.parametrize('months,status',[(12,'supported'),(18,'supported'),(11,'gap'),(0,'gap'),(None,'unknown')])
def test_relevant_duration_is_separate_from_general_years(months,status):
    data=evidence(); data['work_examples'][0]['months']=months
    assert compare(requirement(),data)['status']==status


def test_duties_do_not_imply_grade_equivalence():
    data=evidence(); data['work_examples'][0]['grade_equivalences']=[]
    assert compare(requirement(),data)['status']=='unknown'
    data['work_examples'][0]['grade_equivalences']=[dict(system='GS',grade='09',source='Fictional higher-grade claim')]
    assert compare(requirement(),data)['status']=='unknown' # no implicit hierarchy


def test_general_skills_and_missing_work_examples_do_not_satisfy_specialized_work():
    data=evidence(); data['work_examples']=[]
    assert compare(requirement(),data)['status']=='unknown'
    del data['work_examples']; data['schema_version']=3
    assert compare(requirement(),data)['status']=='unknown'
    assert compare(requirement(),None)['status']=='unknown'


def test_examples_are_not_summed_or_duties_combined():
    data=evidence(); first=data['work_examples'][0]
    first['months']=6
    second=deepcopy(first); second['id']='different-example'
    data['work_examples'].append(second)
    assert compare(requirement(),data)['status']=='gap'
    first['months']=second['months']=24
    first['activities']=['financial_data_analysis']
    second['activities']=['accounting_problem_resolution','automated_financial_systems']
    assert compare(requirement(),data)['status']=='unknown'


def test_unsupported_alternative_and_other_grade_are_not_mixed():
    job=dict(ats_type='usajobs',description=description()+' Specialized Experience GS-11: Unsupported higher-grade duties.')
    result=assess(job,evidence(),extract_requirements(job,profile()))
    assert [p['comparison']['status'] for p in result['path_assessments']]==['supported','unknown']


@pytest.mark.parametrize('change',['negation','extra','waiver'])
def test_partial_or_conditional_specialized_text_is_not_accepted(change):
    text=description()
    if change=='negation': text=text.replace('One year','Not required: One year')
    if change=='extra': text=text.replace('(GS-07).','(GS-07). Must also supervise a team.')
    if change=='waiver': text=text.replace('One year','One year unless waived')
    job=dict(ats_type='usajobs',description=text)
    result=assess(job,evidence(),extract_requirements(job,profile()))
    assert result['path_assessments'][0]['comparison']['status']=='unknown'


def test_other_career_vocabulary_uses_identical_engine():
    p=profile()
    p['qualification_paths']['leaf_rules'].append(dict(pattern=r'One year developing and testing software at level (?P<grade>\d+)\.',
        requirement=dict(op='specialized_experience',activities=['software_delivery'],minimum_months=12,
                         grade_system='example-level',grade='$grade')))
    data=evidence(); data['work_examples']=[dict(id='fictional-software-assignment',activities=['software_delivery'],
        months=14,grade_equivalences=[dict(system='example-level',grade='2',source='Fictional explicit level')],
        source='Fictional assignment doing these duties for 14 months')]
    job=dict(ats_type='usajobs',description='Qualifications: Specialized Experience GS-09: One year developing and testing software at level 2.')
    result=assess(job,data,extract_requirements(job,p))
    assert result['path_assessments'][0]['comparison']['status']=='supported'


@pytest.mark.parametrize('months',[-1,True,float('nan'),'12'])
def test_invalid_durations(months):
    data=evidence(); data['work_examples'][0]['months']=months
    with pytest.raises(ValueError): validate_evidence(data)


def test_duplicate_evidence_and_unsourced_grade_rejected():
    data=evidence(); data['work_examples'].append(deepcopy(data['work_examples'][0]))
    with pytest.raises(ValueError): validate_evidence(data)
    data=evidence(); data['work_examples'][0]['grade_equivalences'][0]['source']=''
    with pytest.raises(ValueError): validate_evidence(data)
    p=profile(); p['qualification_paths']['leaf_rules'][-1]['requirement']['minimum_months']=0
    with pytest.raises(ValueError): resolve_profile(p)


def test_database_round_trip_revision_and_snapshot_replay(tmp_path):
    url=f'sqlite:///{tmp_path / "work.db"}'
    run_migrations(url); factory=build_session_factory(url)
    try:
        with factory() as session:
            person=ApplicantRepository(session).create_from_payload(payload())
            bundle=json.loads(Path('data/search_policy_sample.json').read_text())
            PolicyRepository(session).save(person.id,bundle['policy'],bundle['strategies'])
            session.add(JsonJobNormalizer.normalize(dict(source_job_id='fixture',title='Accountant',
                ats_type='usajobs',description=description())))
            session.commit(); identifier=person.id
        with factory() as session:
            repo=EvaluationRepository(session)
            original=repo.evaluate_jobs(identifier,parser_profile=profile())[0][0]
            snapshot=deepcopy(original.input_context)
            assert original.reasons[0]['assessment']['path_assessments'][0]['comparison']['status']=='supported'
            changed=evidence(); changed['work_examples'][0]['grade_equivalences']=[]
            ApplicantRepository(session).update_from_payload(identifier,dict(experience_evidence=changed))
            session.flush()
            revised=repo.evaluate_jobs(identifier,parser_profile=profile())[0][0]
            assert revised.id!=original.id
            assert revised.reasons[0]['assessment']['path_assessments'][0]['comparison']['status']=='unknown'
            assert original.input_context==snapshot and tier_rules.evaluate(snapshot).reasons==original.reasons
            assert repo.evaluate_jobs(identifier,parser_profile=profile())[1]['unchanged']==1
    finally: factory.kw['bind'].dispose()
