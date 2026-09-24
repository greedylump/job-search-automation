import json
from copy import deepcopy
from pathlib import Path

import pytest

from jobsearch.evaluation.qualification import extract_requirements, assess, compare, validate_evidence
from jobsearch.evaluation.parser_profiles import load_profile, resolve_profile
from jobsearch.evaluation import tier_rules
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.policy_repository import PolicyRepository
from jobsearch.storage.evaluation_repository import EvaluationRepository
from jobsearch.storage.database import build_session_factory
from jobsearch.scripts.init_db import run_migrations
from jobsearch.normalization.json_normalizer import JsonJobNormalizer


def applicant():
    return json.loads(Path('data/accounting_qualifications_sample.json').read_text(encoding='utf-8'))


def profile():
    return load_profile('data/requirement_parser_federal_paths.json')


def job(text):
    return dict(ats_type='usajobs', description='Qualifications: '+text)


def evaluate(text, evidence=None):
    target=job(text)
    parsed=extract_requirements(target, profile())
    return parsed, assess(target, applicant()['experience_evidence'] if evidence is None else evidence, parsed)


def test_basic_degree_alternative_does_not_prove_grade_experience():
    text=("Basic Requirement for Example: A. Degree: Bachelor's degree (or higher degree) in accounting; "
          'or a related degree supplemented by credits. OR B. Combination of education and experience. '
          'In addition to meeting the basic requirement above, additional requirements apply. '
          'Specialized Experience, GS-09: One year of specialized experience at GS-07. '
          'OR Education: Unrecognized graduate route. '
          'Specialized Experience GS-11: One year of specialized experience at GS-09.')
    parsed, result=evaluate(text)
    paths=result['path_assessments']
    assert [(p['kind'],p['grade'],p['comparison']['status']) for p in paths] == [
        ('basic',None,'supported'),('grade','09','unknown'),('grade','11','unknown')]
    assert result['status']=='unknown' and not parsed['complete']
    assert parsed['path_analysis']['paths'][1]['tree']['op']=='any'
    # All nested offsets still address the unmodified original description.
    def check(node):
        span=node['evidence']; source=job(text)['description']
        assert source[span['start']:span['end']]==span['text']
        for child in node.get('children',[]): check(child)
    for path in parsed['path_analysis']['paths']: check(path['tree'])


def test_grade_routes_do_not_mix_and_plain_grade_references_are_not_headings():
    _, result=evaluate("Specialized Experience GS-09: Bachelor's degree in accounting. "
                       'Specialized Experience GS-11: Certified Internal Auditor. '
                       'Equivalent to GS-07: not an advertised grade heading.')
    paths=result['path_assessments']
    assert len(paths)==2 and paths[0]['comparison']['status']=='supported'
    assert paths[1]['comparison']['status']=='unknown'
    assert result['status']=='unknown'


@pytest.mark.parametrize('prefix',['No ', 'Preferred: ', 'If eligible, ', 'Not required: '])
def test_qualifiers_cannot_be_discarded(prefix):
    _, result=evaluate('Specialized Experience GS-09: '+prefix+"Bachelor's degree in accounting.")
    assert result['path_assessments'][0]['comparison']['status']=='unknown'


def test_unsupported_or_branch_stays_viable_after_known_mismatch():
    evidence=applicant()['experience_evidence']
    evidence['qualifications'][0]['attained']=False
    _, result=evaluate("Specialized Experience GS-09: Bachelor's degree in accounting. "
                       'OR Education: Other qualification route.', evidence)
    tree=result['path_assessments'][0]['comparison']
    assert tree['status']=='unknown' and tree['children'][0]['status']=='mismatch'


def test_credential_examination_and_current_status_are_separate():
    evidence=applicant()['experience_evidence']
    node=dict(op='credential',name='Certified Public Accountant',current=False,by_examination=False)
    assert compare(node,evidence)['status']=='supported'
    node['by_examination']=True
    assert compare(node,evidence)['status']=='unknown'
    evidence['qualifications'][1]['by_examination']=True
    assert compare(node,evidence)['status']=='supported'
    node['current']=True
    assert compare(node,evidence)['status']=='unknown'
    evidence['qualifications'][1]['current']=False
    assert compare(node,evidence)['status']=='mismatch'


def test_degree_does_not_imply_credits_other_fields_or_exhaustive_absence():
    evidence=applicant()['experience_evidence']
    assert compare(dict(op='credits',field='accounting',minimum=24),evidence)['status']=='unknown'
    assert compare(dict(op='degree',field='nursing',levels=['bachelor']),evidence)['status']=='unknown'
    evidence['qualifications'][0]['attained']=False
    assert compare(dict(op='degree',field='accounting',levels=['bachelor','master']),evidence)['status']=='unknown'
    assert compare(dict(op='degree',field='accounting',levels=['bachelor']),evidence)['status']=='mismatch'


def test_explicit_credits_are_not_double_counted_or_inferred_from_degree():
    evidence=applicant()['experience_evidence']
    evidence['qualifications'].append(dict(kind='credits',field='accounting',semester_hours=24,source='Fictional transcript'))
    _,result=evaluate('Specialized Experience GS-09: 24 semester hours in accounting.',evidence)
    assert result['path_assessments'][0]['comparison']['status']=='supported'
    assert compare(dict(op='credits',field='accounting',minimum=25),evidence)['status']=='mismatch'
    assert compare(dict(op='credits',field='auditing',minimum=24),evidence)['status']=='unknown'
    evidence['qualifications'].append(deepcopy(evidence['qualifications'][-1]))
    with pytest.raises(ValueError,match='Duplicate'): validate_evidence(evidence)


def test_nursing_uses_same_typed_comparison_and_configurable_grammar():
    evidence=applicant()['experience_evidence']
    evidence['qualifications']=[dict(kind='credential',name='Registered Nurse',attained=True,
        current=True,by_examination=True,source='Fictional nursing license')]
    _, result=evaluate('Specialized Experience GS-09: Registered Nurse, obtained through written examination.',evidence)
    assert result['path_assessments'][0]['comparison']['status']=='supported'


@pytest.mark.parametrize('field,value',[('attained','yes'),('current',1),('by_examination',[])])
def test_invalid_credential_assertions(field,value):
    evidence=applicant()['experience_evidence']; evidence['qualifications'][1][field]=value
    with pytest.raises(ValueError): validate_evidence(evidence)


def test_invalid_scope_config_and_templates():
    p=profile(); p['qualification_paths']['grade_heading']='.*'
    with pytest.raises(ValueError): resolve_profile(p)
    p=profile(); p['qualification_paths']['leaf_rules'][0]['requirement']['field']='$missing'
    with pytest.raises(ValueError): resolve_profile(p)


def test_typed_evidence_database_history_and_profile_snapshot(tmp_path):
    url=f'sqlite:///{tmp_path / "paths.db"}'
    run_migrations(url); factory=build_session_factory(url)
    try:
        with factory() as session:
            person=ApplicantRepository(session).create_from_payload(applicant())
            bundle=json.loads(Path('data/search_policy_sample.json').read_text())
            PolicyRepository(session).save(person.id,bundle['policy'],bundle['strategies'])
            session.add(JsonJobNormalizer.normalize(dict(source_job_id='fixture',title='Accountant',ats_type='usajobs',
                description="Qualifications: Specialized Experience GS-09: Bachelor's degree in accounting.")))
            session.commit(); identifier=person.id
        with factory() as session:
            repo=EvaluationRepository(session)
            first=repo.evaluate_jobs(identifier,parser_profile=profile())[0][0]
            snapshot=deepcopy(first.input_context)
            assert first.reasons[0]['assessment']['path_assessments'][0]['comparison']['status']=='supported'
            revised=applicant()['experience_evidence']; revised['qualifications'][0]['attained']=False
            ApplicantRepository(session).update_from_payload(identifier,dict(experience_evidence=revised))
            session.flush()
            second=repo.evaluate_jobs(identifier,parser_profile=profile())[0][0]
            assert second.id!=first.id
            assert second.reasons[0]['assessment']['path_assessments'][0]['comparison']['status']=='mismatch'
            assert first.input_context==snapshot and tier_rules.evaluate(snapshot).reasons==first.reasons
            assert first.queue_state==second.queue_state=='unresolved'
            assert repo.evaluate_jobs(identifier,parser_profile=profile())[1]['unchanged']==1
    finally: factory.kw['bind'].dispose()
