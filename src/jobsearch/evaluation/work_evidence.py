"""Compare specialized duties against one explicitly documented work example."""
import math


def validate(examples):
    if not isinstance(examples, list):
        raise ValueError('work_examples must be a list')
    identifiers = set()
    for row in examples:
        if not isinstance(row, dict) or set(row) != {'id', 'activities', 'months', 'grade_equivalences', 'source'}:
            raise ValueError('Invalid work example fields')
        for field in ('id', 'source'):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError('Work example IDs and sources must be nonblank')
        if row['id'] in identifiers:
            raise ValueError('Duplicate work example ID')
        identifiers.add(row['id'])
        activities = row['activities']
        if not isinstance(activities, list) or not activities or any(not isinstance(a, str) or not a.strip() for a in activities):
            raise ValueError('Activities must be nonblank stable identifiers')
        if len(set(activities)) != len(activities):
            raise ValueError('Duplicate work activity')
        months = row['months']
        if months is not None and (type(months) not in (int, float) or not math.isfinite(months) or months < 0):
            raise ValueError('Relevant months must be finite nonnegative numbers or null')
        if not isinstance(row['grade_equivalences'], list):
            raise ValueError('grade_equivalences must be a list')
        seen = set()
        for grade in row['grade_equivalences']:
            if not isinstance(grade, dict) or set(grade) != {'system', 'grade', 'source'}:
                raise ValueError('Grade equivalence requires system, grade, source')
            if any(not isinstance(v, str) or not v.strip() for v in grade.values()):
                raise ValueError('Grade equivalence assertions must be explicit nonblank strings')
            key = (grade['system'], grade['grade'])
            if key in seen: raise ValueError('Duplicate grade equivalence')
            seen.add(key)


def compare(node, evidence):
    examples = (evidence or {}).get('work_examples', [])
    comparisons = []
    for row in examples:
        missing = sorted(set(node['activities']) - set(row['activities']))
        grades = [g for g in row['grade_equivalences'] if
                  (g['system'], g['grade']) == (node['grade_system'], node['grade'])]
        duration = ('unknown' if row['months'] is None else
                    'supported' if row['months'] >= node['minimum_months'] else 'gap')
        status = 'unknown' if missing or not grades else duration
        comparisons.append(dict(status=status, example_id=row['id'], applicant_evidence=row,
            checks=dict(activities='unknown' if missing else 'supported', duration=duration,
                        grade='supported' if grades else 'unknown'),
            missing_activities=missing, grade_evidence=grades))
    states = [c['status'] for c in comparisons]
    status = 'supported' if 'supported' in states else 'gap' if 'gap' in states else 'unknown'
    return dict(status=status, requirement=node, work_examples=comparisons,
        explanation='Duties, relevant duration, and explicit grade equivalence must hold in the same work example. '
                    'Examples are not summed or combined; omitted duties and grade equivalence remain unknown.')
