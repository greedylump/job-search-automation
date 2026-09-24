import json
from pathlib import Path

import pytest

from jobsearch.evaluation.parser_profiles import load_profile, resolve_profile
from jobsearch.evaluation.qualification import assess, extract_requirements, queue_state


BRIDGE = 'In addition to meeting the basic requirement above, you must also meet the qualification requirements listed below: '


def profile():
    return load_profile('data/requirement_parser_composed.json')


def evidence():
    return json.loads(Path('data/accounting_work_sample.json').read_text())['experience_evidence']


def text():
    return ("Qualifications: Basic Requirement for Example: Bachelor's degree in accounting. " + BRIDGE +
            'Specialized Experience GS-09: Certified Public Accountant. '
            'Specialized Experience GS-11: Unsupported alternative.')


def run(description=None, data=None):
    job=dict(ats_type='usajobs',description=text() if description is None else description)
    parsed=extract_requirements(job,profile())
    return parsed, assess(job,evidence() if data is None else data,parsed)


def test_basic_and_any_grade_with_complete_coverage():
    parsed,result=run()
    assert parsed['complete'] and not parsed['ambiguous']
    assert result['status']=='supported'
    assert [g['comparison']['status'] for g in result['overall_qualification']['grades']]==['supported','unknown']
    assert queue_state(result,[dict(check='eligibility',outcome='review')])=='unresolved'
    assert queue_state(result,[dict(check='availability',outcome='reject')])=='do_not_pursue'


def test_basic_requirement_cannot_be_rescued_by_grade_alternative():
    data=evidence(); data['qualifications'][0]['attained']=False
    _,result=run(data=data)
    assert result['status']=='mismatch'
    assert all(g['comparison']['status']=='mismatch' for g in result['overall_qualification']['grades'])


def test_basic_degree_alone_cannot_establish_any_grade():
    data=evidence(); data['qualifications'][1]['attained']=False
    _,result=run(data=data)
    assert result['status']=='unknown' # unsupported grade alternative remains viable


@pytest.mark.parametrize('extra',[
    'Qualifications: Conditional eligibility applies. ',
    '\n\nEducation: Foreign education must meet additional conditions.',
    '\n\nRequirements: Applicants must satisfy an additional requirement.',
])
def test_uncovered_source_text_blocks_pass_and_reject(extra):
    description=(text().replace('Qualifications: ',extra) if extra.startswith('Qualifications:') else text()+extra)
    parsed,result=run(description)
    assert not parsed['complete'] and result['status']=='unknown'
    assert parsed['composition']['unparsed']
    for span in parsed['composition']['unparsed']:
        assert description[span['start']:span['end']]==span['text']
    data=evidence(); data['qualifications'][0]['attained']=False
    assert run(description,data)[1]['status']=='unknown'


@pytest.mark.parametrize('mutation',['bridge','duplicate_grade','missing_basic','duplicate_section','reversed'])
def test_ambiguous_scope_is_not_composed(mutation):
    description=text()
    if mutation=='bridge': description=description.replace(BRIDGE,'In addition to meeting the basic requirement above, exceptions apply: ')
    if mutation=='duplicate_grade': description=description.replace('GS-11','GS-09')
    if mutation=='missing_basic': description=description.replace('Basic Requirement for Example:','Entry:')
    if mutation=='duplicate_section': description+='\n\nQualifications: Other grade routes.'
    if mutation=='reversed': description='Qualifications: Specialized Experience GS-07: Other duties. '+description[len('Qualifications: '):]
    parsed,result=run(description)
    assert not parsed['complete'] and result['status']=='unknown'
    assert parsed['composition']['blockers']


def test_basic_alternatives_remain_inside_shared_basic_requirement():
    description=text().replace("Bachelor's degree in accounting.","A. Degree: Bachelor's degree in nursing; or Bachelor's degree in accounting.")
    assert run(description)[1]['status']=='supported'


def test_profile_scope_validation():
    p=profile(); p['qualification_composition']['bridge']='.*'
    with pytest.raises(ValueError): resolve_profile(p)


def test_old_profile_stays_component_only():
    job=dict(ats_type='usajobs',description=text())
    old=load_profile('data/requirement_parser_specialized.json')
    parsed=extract_requirements(job,old)
    assert 'composition' not in parsed
    assert assess(job,evidence(),parsed)['status']=='unknown'
