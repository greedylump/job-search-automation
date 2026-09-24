"""Typed applicant assertions; omitted facts never mean absent qualifications."""
import math
import re
from jobsearch.evaluation.rules import normalized


def validate(facts):
    if not isinstance(facts, list):
        raise ValueError('qualifications must be a list')
    seen = set()
    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError('Qualification facts must be objects')
        kind = fact.get('kind')
        shapes = {
            'degree': {'kind', 'level', 'field', 'attained', 'source'},
            'credential': {'kind', 'name', 'attained', 'current', 'by_examination', 'source'},
            'credits': {'kind', 'field', 'semester_hours', 'source'},
        }
        optional = {'education_country', 'recognized_in', 'transcript_available'} if kind in ('degree','credits') else set()
        if not isinstance(kind, str) or kind not in shapes or not shapes[kind] <= set(fact) or set(fact) - shapes[kind] - optional:
            raise ValueError('Invalid qualification fact fields')
        if 'education_country' in fact and fact['education_country'] is not None:
            if not isinstance(fact['education_country'], str) or not re.fullmatch('[A-Z]{2}', fact['education_country']):
                raise ValueError('Education country must be a two-letter uppercase code or null')
        if fact.get('recognized_in') is not None:
            countries = fact['recognized_in']
            if not isinstance(countries, list) or any(not isinstance(v,str) or not re.fullmatch('[A-Z]{2}',v) for v in countries):
                raise ValueError('recognized_in must be a country-code list or null')
            if len(countries) != len(set(countries)): raise ValueError('Duplicate recognition country')
        if 'transcript_available' in fact and fact['transcript_available'] is not None and type(fact['transcript_available']) is not bool:
            raise ValueError('Transcript availability must be boolean or null')
        for key in shapes[kind] - {'attained', 'current', 'by_examination', 'semester_hours'}:
            if not isinstance(fact[key], str) or not fact[key].strip():
                raise ValueError('Qualification names and sources must be nonblank')
        for key in ('attained', 'current', 'by_examination'):
            if key in fact and fact[key] is not None and type(fact[key]) is not bool:
                raise ValueError('Qualification assertions must be boolean or null')
        if kind == 'credits':
            value = fact['semester_hours']
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or value < 0):
                raise ValueError('Semester hours must be finite nonnegative numbers or null')
        if kind == 'credential' and fact['attained'] is False and (fact['current'] is True or fact['by_examination'] is True):
            raise ValueError('Absent credentials cannot be current or attained by examination')
        identity = (kind, normalized(fact.get('field', fact.get('name', ''))), normalized(fact.get('level', '')))
        if identity in seen:
            raise ValueError('Duplicate qualification facts; supply one aggregate assertion per qualification')
        seen.add(identity)


def compare(node, evidence):
    facts = (evidence or {}).get('qualifications', [])
    kind = node['op']
    relevant = []
    states = []
    def recognition(state, row):
        if state != 'supported' or not kind.startswith('recognized_'):
            return state
        return 'supported' if row.get('education_country') == node['country'] or node['country'] in (row.get('recognized_in') or []) else 'unknown'

    if kind in ('degree','recognized_degree'):
        # Each allowed level is a separate alternative. No implicit hierarchy.
        for level in node['levels']:
            row = next((r for r in facts if r['kind'] == 'degree' and
                        normalized(r['level']) == normalized(level) and
                        normalized(r['field']) == normalized(node['field'])), None)
            if row: relevant.append(row)
            states.append(recognition('unknown' if row is None or row['attained'] is None else
                          'supported' if row['attained'] else 'mismatch', row))
    elif kind == 'credential':
        row = next((r for r in facts if r['kind'] == 'credential' and
                    normalized(r['name']) == normalized(node['name'])), None)
        if row:
            relevant.append(row)
            required = ['attained'] + [k for k in ('current', 'by_examination') if node.get(k)]
            states = ['mismatch' if any(row[k] is False for k in required) else
                      'unknown' if any(row[k] is None for k in required) else 'supported']
    elif kind in ('credits','recognized_credits'):
        row = next((r for r in facts if r['kind'] == 'credits' and
                    normalized(r['field']) == normalized(node['field'])), None)
        if row:
            relevant.append(row)
            states = [recognition('unknown' if row['semester_hours'] is None else
                      'supported' if row['semester_hours'] >= node['minimum'] else 'mismatch',row)]
    status = ('supported' if 'supported' in states else
              'mismatch' if states and all(s == 'mismatch' for s in states) else 'unknown')
    return dict(status=status, requirement=node, applicant_evidence=relevant,
                explanation='Typed qualification assertions only; omitted evidence or unresolved text stays unknown.')
