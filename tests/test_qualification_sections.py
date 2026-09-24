from copy import deepcopy

import pytest

from jobsearch.evaluation.parser_profiles import load_profile, resolve_profile
from jobsearch.evaluation.qualification import extract_requirements, assess


def profile():
    return load_profile('data/requirement_parser_federal.json')


def extract(text, ats='usajobs'):
    return extract_requirements(dict(description=text, ats_type=ats), profile())


def test_sections_keep_alternatives_grades_and_original_spans():
    text = (
        'Summary: Certified Public Accountant mentioned in advertising.\n\n'
        "Qualifications: Bachelor's degree in accounting OR equivalent combination of education and experience. "
        'In addition to meeting the basic requirement above, one year of specialized experience at GS-09. '
        'OR Education: three full years of graduate education.\n\n'
        'Duties: Certified Internal Auditor liaison.\n\n'
        'Education: 24 semester hours in accounting or auditing; Certified Public Accountant.\n\n'
        'Application closes: 2026-10-10'
    )
    parsed = extract(text)
    sections = parsed['section_analysis']['sections']
    assert [s['label'] for s in sections] == ['Qualifications', 'Education']
    clauses = [c for section in sections for c in section['clauses']]
    assert {'education', 'specialized_experience', 'grade_reference', 'education_duration',
            'education_credits', 'credential', 'alternative', 'additional_requirement'} <= {c['kind'] for c in clauses}
    assert [c['captures']['credential'] for c in clauses if c['kind'] == 'credential'] == ['Certified Public Accountant']
    for section in sections:
        for span in [section['evidence'], *section['unparsed'], *(c['evidence'] for c in section['clauses'])]:
            assert text[span['start']:span['end']] == span['text']
        assert all(c['scope_status'] == 'unresolved' for c in section['clauses'])
    assert parsed['ambiguous'] and not parsed['complete']


def test_unparsed_content_and_external_references_are_not_satisfied():
    parsed = extract('Qualifications: Basic requirement: https://example.org/requirements '
                     'GS-12 requires agency-specific experience.\n\nEducation: See questionnaire.')
    section = parsed['section_analysis']['sections'][0]
    assert any(c['kind'] == 'external_reference' for c in section['clauses'])
    assert 'requires agency-specific experience.' in ''.join(s['text'] for s in section['unparsed'])
    assert not parsed['complete']


def test_federal_alternative_prevents_false_mismatch_from_isolated_block():
    job = dict(ats_type='usajobs', description='Qualifications: A degree OR experience.\n\n'
               'Requirements: Commercial experience: accounting: 5+ years\n\nEducation: Degree alternative applies.')
    evidence = dict(schema_version=1, job_exclusions=[], skills=[dict(skill='accounting',
        commercial_years_min=0, commercial_years_max=0, expertise=None, source='Fictional applicant')])
    parsed = extract_requirements(job, profile())
    assert assess(job, evidence, parsed)['status'] == 'unknown'
    job['ats_type'] = 'other'
    job['description'] = 'Requirements: Commercial experience: accounting: 5+ years'
    assert assess(job, evidence, extract_requirements(job, profile()))['status'] == 'mismatch'


def test_patterns_are_reusable_and_snapshotted():
    p = profile()
    p['qualification_sections']['clauses'] = [dict(name='nursing-license', kind='credential',
        pattern=r'(?P<credential>Registered Nurse)')]
    result = extract_requirements(dict(ats_type='usajobs', description='Qualifications: Registered Nurse license.'), p)
    p['qualification_sections']['clauses'].clear()
    assert result['parser_profile']['qualification_sections']['clauses']
    assert result['section_analysis']['sections'][0]['clauses'][0]['captures'] == {'credential': 'Registered Nurse'}


@pytest.mark.parametrize('pattern', ['(', '(unnamed)', '.*'])
def test_invalid_clause_patterns(pattern):
    p = profile()
    p['qualification_sections']['clauses'][0]['pattern'] = pattern
    with pytest.raises(ValueError):
        resolve_profile(p)


def test_missing_sections_and_other_sources_are_explicit():
    assert extract('Summary: Qualifications: no paragraph boundary')['section_analysis']['sections'] == []
    assert not extract('Qualifications: one year of specialized experience', 'other')['section_analysis']['applicable']


def test_no_substitution_and_combined_paths_are_retained_without_flattening():
    parsed = extract('Qualifications: GS-11 one year of specialized experience. OR Combination of Education and Experience. '
                     'GS-12 no substitution of education for experience is permitted.')
    clauses = parsed['section_analysis']['sections'][0]['clauses']
    assert {'combined_path', 'substitution_restriction'} <= {c['kind'] for c in clauses}
    assert [c['captures']['grade'] for c in clauses if c['kind'] == 'grade_reference'] == ['11', '12']
    assert not parsed['complete']
