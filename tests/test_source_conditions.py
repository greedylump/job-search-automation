import json
from copy import deepcopy
from pathlib import Path

import pytest

from jobsearch.evaluation.qualification import assess, extract_requirements, compare, validate_evidence, queue_state
from jobsearch.evaluation.parser_profiles import load_profile, resolve_profile
from jobsearch.evaluation import tier_rules
from jobsearch.storage.database import build_session_factory
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.policy_repository import PolicyRepository
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.scripts.init_db import run_migrations


def payload():
    return json.loads(Path('data/accounting_conditions_sample.json').read_text())


def profile():
    p=load_profile('data/requirement_parser_conditions.json')
    p['qualification_conditions'][0]['pattern']=r'Who May Apply: US Citizens\. Resume evidence and education-path transcripts required\.'
    p['qualification_conditions'][1]['pattern']=r'Foreign education used to qualify requires US recognition\.'
    return p


def job():
    return dict(ats_type='usajobs',description='Qualifications: Who May Apply: US Citizens. Resume evidence and education-path transcripts required. '
        "Basic Requirement for Example: Bachelor's degree in accounting. "
        'In addition to meeting the basic requirement above, you must also meet the qualification requirements listed below: '
        'Specialized Experience GS-09: Certified Public Accountant.\n\n'
        'Education: Foreign education used to qualify requires US recognition.')


def evaluate(data=None, target=None, citizenships=None):
    target=target or job()
    parsed=extract_requirements(target,profile())
    return parsed,assess(target,payload()['experience_evidence'] if data is None else data,parsed,
                         eligibility=dict(citizenships=['US'] if citizenships is None else citizenships))


def test_domestic_degree_resolves_condition_without_inventing_transcript():
    parsed,result=evaluate()
    assert parsed['complete'] and result['status']=='supported'
    assert result['source_conditions'][0]['status']=='supported'
    assert result['source_conditions'][1]['status']=='preparation_required'
    assert payload()['experience_evidence']['qualifications'][0]['transcript_available'] is None
    assert queue_state(result,[dict(check='geography',outcome='review')])=='unresolved'


@pytest.mark.parametrize('country,recognized,status',[(None,None,'unknown'),('CA',None,'unknown'),
    ('CA',[],'unknown'),('CA',['US'],'supported'),('US',None,'supported'),('CA',['GB'],'unknown')])
def test_education_origin_and_recognition(country,recognized,status):
    data=payload()['experience_evidence']
    data['qualifications'][0].update(education_country=country,recognized_in=recognized)
    assert evaluate(data)[1]['status']==status


def test_missing_optional_metadata_stays_unknown():
    data=payload()['experience_evidence']
    for key in ['education_country','recognized_in','transcript_available']:
        del data['qualifications'][0][key]
    assert evaluate(data)[1]['status']=='unknown'


def test_credit_recognition_belongs_to_the_credit_record():
    data=payload()['experience_evidence']
    data['qualifications'].append(dict(kind='credits',field='accounting',semester_hours=24,
        education_country='CA',recognized_in=None,source='Fictional transcript'))
    node=dict(op='recognized_credits',field='accounting',minimum=24,country='US')
    assert compare(node,data)['status']=='unknown' # domestic degree cannot clear these credits
    data['qualifications'][-1]['recognized_in']=['US']
    assert compare(node,data)['status']=='supported'


def test_country_vocabulary_is_configuration_not_applicant_logic():
    p=profile(); target=job(); data=payload()['experience_evidence']
    target['description']=target['description'].replace('US Citizens','Canadian Citizens').replace('US recognition','Canadian recognition')
    p['qualification_conditions'][0].update(country='CA',citizenship_values=['CA','Canada'],
        pattern=p['qualification_conditions'][0]['pattern'].replace('US Citizens','Canadian Citizens'))
    p['qualification_conditions'][1].update(country='CA',
        pattern=p['qualification_conditions'][1]['pattern'].replace('US recognition','Canadian recognition'))
    data['qualifications'][0]['education_country']='CA'
    result=assess(target,data,extract_requirements(target,p),eligibility=dict(citizenships=['Canada']))
    assert result['status']=='supported' and result['source_conditions'][0]['status']=='supported'


def test_grade_degree_and_recognition_cannot_come_from_different_records():
    data=payload()['experience_evidence']
    data['qualifications'][0]['attained']=False
    data['qualifications'].append(dict(kind='degree',level='master',field='accounting',attained=True,
        education_country='CA',recognized_in=None,source='Fictional foreign degree without recognition assertion'))
    node=dict(op='recognized_degree',levels=['bachelor','master'],field='accounting',country='US')
    assert compare(node,data)['status']=='unknown'


def test_non_education_alternative_does_not_require_degree_provenance():
    target=job()
    target['description']=target['description'].replace("Bachelor's degree in accounting.",
        "Bachelor's degree in nursing; or Certified Public Accountant.")
    assert evaluate(target=target)[1]['status']=='supported'


@pytest.mark.parametrize('citizenships',[[],['CA']])
def test_missing_citizenship_is_unknown_not_absent(citizenships):
    _,result=evaluate(citizenships=citizenships)
    assert result['status']=='supported'
    assert result['source_conditions'][0]['status']=='unknown'
    assert queue_state(result,[])=='unresolved'


def test_changed_or_additional_conditions_cannot_be_erased():
    target=job(); target['description']=target['description'].replace('US Citizens.','US Citizens unless exempt.')
    parsed,result=evaluate(target=target)
    assert not parsed['complete'] and result['status']=='unknown'
    target=job(); target['description']+=' Additional professional registration is mandatory.'
    assert evaluate(target=target)[1]['status']=='unknown'


def test_transcript_unavailable_is_preparation_not_qualification_failure():
    data=payload()['experience_evidence']; data['qualifications'][0]['transcript_available']=False
    assert evaluate(data)[1]['status']=='supported'


@pytest.mark.parametrize('field,value',[('education_country','United States'),('recognized_in','US'),
    ('recognized_in',['US','US']),('transcript_available','yes')])
def test_invalid_education_metadata(field,value):
    data=payload()['experience_evidence']; data['qualifications'][0][field]=value
    with pytest.raises(ValueError): validate_evidence(data)


def test_ambiguous_rule_matches_do_not_consume_source_text():
    p=profile(); p['qualification_conditions'].append(deepcopy(p['qualification_conditions'][0]))
    parsed=extract_requirements(job(),p)
    assert not parsed['complete']
    p=profile(); p['qualification_conditions'][0]['pattern']='.*'
    with pytest.raises(ValueError): resolve_profile(p)


def test_no_valid_composition_cannot_be_promoted_by_boilerplate():
    target=job(); target['description']=target['description'].replace('Basic Requirement for Example:','Other heading:')
    parsed,result=evaluate(target=target)
    assert not parsed['complete'] and result['status']=='unknown'


def test_database_policy_citizenship_and_education_history(tmp_path):
    url=f'sqlite:///{tmp_path / "conditions.db"}'
    run_migrations(url); factory=build_session_factory(url)
    try:
        with factory() as session:
            person=ApplicantRepository(session).create_from_payload(payload())
            bundle=json.loads(Path('data/search_policy_sample.json').read_text())
            bundle['policy']['eligibility']['citizenships']=['US']
            PolicyRepository(session).save(person.id,bundle['policy'],bundle['strategies'])
            session.add(JsonJobNormalizer.normalize(dict(source_job_id='fixture',title='Accountant',**job())))
            session.commit(); identifier=person.id
        with factory() as session:
            repo=EvaluationRepository(session)
            first=repo.evaluate_jobs(identifier,parser_profile=profile())[0][0]
            snapshot=deepcopy(first.input_context)
            assert first.reasons[0]['assessment']['status']=='supported'
            assert next(r for r in first.reasons if r['check']=='citizenship')['outcome']=='keep'
            assert first.queue_state=='unresolved' and first.tier is None
            revised=payload()['experience_evidence']; revised['qualifications'][0]['education_country']=None
            ApplicantRepository(session).update_from_payload(identifier,dict(experience_evidence=revised)); session.flush()
            second=repo.evaluate_jobs(identifier,parser_profile=profile())[0][0]
            assert first.id!=second.id and second.reasons[0]['assessment']['status']=='unknown'
            assert first.input_context==snapshot and tier_rules.evaluate(snapshot).reasons==first.reasons
            assert repo.evaluate_jobs(identifier,parser_profile=profile())[1]['unchanged']==1
    finally: factory.kw['bind'].dispose()
