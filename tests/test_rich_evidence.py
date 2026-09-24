from copy import deepcopy
import json
from pathlib import Path
import pytest

from jobsearch.evaluation.qualification import compare, assess, extract_requirements, validate_evidence
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.database import build_session_factory
from jobsearch.scripts.init_db import run_migrations
from jobsearch.models import Applicant


def data():
    return json.loads(Path('data/accounting_applicant_sample.json').read_text())['experience_evidence']


def leaf(skill='accounting', minimum=5):
    return dict(op='commercial_years', skill=skill, minimum=minimum)


@pytest.mark.parametrize('needed,status', [(5,'supported'),(8,'supported'),(9,'gap'),(20,'gap')])
def test_approximate_years_are_not_strict_disqualifiers(needed,status):
    assert compare(leaf(minimum=needed), data())['status'] == status


def test_established_absence_unknown_and_projects_differ():
    assert compare(leaf('C#'), data())['status'] == 'mismatch'
    assert compare(leaf('unrecorded skill'), data())['status'] == 'unknown'
    d = data()
    row = d['skills'][0]
    row.update(state='not_established', commercial=None, approximate_years=None)
    assert compare(leaf(), d)['status'] == 'unknown'
    row.update(state='established',commercial=False)
    assert compare(leaf(), d)['status'] == 'mismatch'


def test_depth_duration_and_expertise_are_independent():
    d=data()
    d['skills'][0]['expertise']=None
    assert compare(dict(op='expertise',skill='accounting'),d)['status']=='unknown'
    d['skills'][0]['depth']='exposure'
    assert compare(dict(op='expertise',skill='accounting'),d)['status']=='unknown'


def test_explicit_transferability_keeps_unknown_skill_viable():
    d=data()
    d['skills'][0]['transfers_to']=['budget analysis']
    result=compare(leaf('budget analysis'),d)
    assert result['status']=='adjacent' and result['transferable_evidence']
    assert compare(leaf('tax litigation'),d)['status']=='unknown'


def test_and_or_gap_alternatives_not_mixed():
    d=data()
    branch=dict(op='any',children=[leaf('C#'),leaf('accounting',9)])
    assert compare(branch,d)['status']=='gap'
    assert compare(dict(op='all',children=[leaf('C#'),leaf('accounting',9)]),d)['status']=='mismatch'


@pytest.mark.parametrize('field,value', [('approximate_years',-1),('commercial','true'),('state','expert'),('depth','wizard'),('recency',3)])
def test_invalid_rich_evidence(field,value):
    d=data(); d['skills'][0][field]=value
    with pytest.raises(ValueError): validate_evidence(d)


def test_no_alias_invented_or_double_counted():
    d=data(); d['skills'][0]['aliases']=['C#']
    with pytest.raises(ValueError,match='alias'): validate_evidence(d)


def test_database_round_trip_and_schema_version_one_compatibility(tmp_path):
    url=f'sqlite:///{tmp_path / "rich.db"}'
    run_migrations(url)
    factory=build_session_factory(url)
    try:
        with factory() as session:
            payload=json.loads(Path('data/accounting_applicant_sample.json').read_text())
            applicant=ApplicantRepository(session).create_from_payload(payload)
            session.commit(); identifier=applicant.id
        with factory() as session:
            saved=session.get(Applicant,identifier).experience_evidence
            assert saved==payload['experience_evidence']
            assert compare(leaf(),saved)['status']=='supported'
            old=dict(schema_version=1,skills=[dict(skill='accounting',commercial_years_min=3,commercial_years_max=3,expertise=None,source='Fictional')],job_exclusions=[])
            assert compare(leaf(),old)['status']=='mismatch'
    finally: factory.kw['bind'].dispose()


def test_parser_gap_and_incomplete_coverage_are_distinct():
    parsed=extract_requirements({'description':'Requirements: Commercial experience: accounting: 9+ years'})
    assert assess({},data(),parsed)['status']=='gap'
    parsed=extract_requirements({'description':'Requirements: Commercial experience: accounting: 5+ years Other requirements: Unparsed condition.'})
    assert assess({},data(),parsed)['status']=='unknown'
