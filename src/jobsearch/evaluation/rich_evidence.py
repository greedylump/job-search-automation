"""Career-neutral reported experience. Approximation is never a strict bound."""
import math
from jobsearch.evaluation.rules import normalized


STATES = {"established", "none", "no_meaningful_professional", "not_established", "limited", "adjacent"}


def validate(value):
    if isinstance(value, dict) and type(value.get('schema_version')) is int and value['schema_version'] == 4:
        from jobsearch.evaluation.work_evidence import validate as validate_work
        if 'work_examples' not in value:
            raise ValueError('Evidence schema 4 requires work_examples')
        validate_work(value['work_examples'])
        return validate({**{k: v for k, v in value.items() if k != 'work_examples'}, 'schema_version': 3})
    if isinstance(value, dict) and type(value.get('schema_version')) is int and value['schema_version'] == 3:
        from jobsearch.evaluation.qualification_facts import validate as validate_facts
        if 'qualifications' not in value:
            raise ValueError('Evidence schema 3 requires qualifications')
        validate_facts(value['qualifications'])
        return validate({**{k: v for k, v in value.items() if k != 'qualifications'}, 'schema_version': 2})
    required = {"schema_version", "skills", "job_exclusions", "comparison_policy"}
    if not isinstance(value, dict) or set(value) - (required | {"background"}) or not required <= set(value):
        raise ValueError("Rich evidence requires schema_version, skills, job_exclusions, comparison_policy")
    if type(value['schema_version']) is not int or value['schema_version'] != 2:
        raise ValueError("Expected evidence schema 2")
    if value['comparison_policy'] != {"numeric_shortfall": "hold", "transferable": "hold"}:
        raise ValueError("Schema 2 requires non-rejecting holds for numeric shortfalls and transferable experience")
    if not isinstance(value['skills'], list):
        raise ValueError("skills must be a list")
    seen = set()
    for row in value['skills']:
        fields = {'skill', 'aliases', 'state', 'commercial', 'approximate_years', 'depth', 'recency', 'expertise', 'transfers_to', 'source'}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Invalid rich skill fields")
        for field in ('skill', 'source'):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError("Skill and evidence source must be nonblank")
        for field in ('aliases', 'transfers_to'):
            if not isinstance(row[field], list) or any(not isinstance(v, str) or not v.strip() for v in row[field]):
                raise ValueError("Aliases and transfer targets must be nonblank string lists")
        keys = [normalized(v) for v in [row['skill'], *row['aliases']]]
        if len(keys) != len(set(keys)) or set(keys) & seen:
            raise ValueError("Duplicate/ambiguous evidence skill alias")
        seen.update(keys)
        if row['state'] not in STATES or row['depth'] not in {'core', 'working', 'exposure', 'unknown'}:
            raise ValueError("Invalid state or depth")
        for field in ('commercial', 'expertise'):
            if row[field] is not None and type(row[field]) is not bool:
                raise ValueError("Commercial/expertise values must be boolean or null")
        if row['recency'] is not None and (not isinstance(row['recency'], str) or not row['recency'].strip()):
            raise ValueError("Recency must be nonblank text or null")
        years = row['approximate_years']
        if years is not None:
            if type(years) not in (float, int) or not math.isfinite(years) or years < 0:
                raise ValueError("Approximate years must be finite nonnegative numeric values or null")
            if row['commercial'] is not True or row['state'] not in {'established', 'limited'}:
                raise ValueError("Commercial duration requires explicitly established commercial experience")
        if row['state'] == 'none' and row['commercial'] is True:
            raise ValueError("Absent experience cannot be commercial experience")
    if 'background' in value and (not isinstance(value['background'], list) or any(not isinstance(v, str) for v in value['background'])):
        raise ValueError("Background must be a list of source statements")
    # Reuse the existing exclusion schema without calling the version dispatcher.
    from jobsearch.evaluation.qualification import validate_evidence
    validate_evidence(dict(schema_version=1, skills=[], job_exclusions=value['job_exclusions']))


def compare(tree, evidence, profile):
    validate(evidence)
    from jobsearch.evaluation.qualification import skill_key
    def key(value):
        return skill_key(value, profile)
    rows = {}
    for row in evidence['skills']:
        for name in [row['skill'], *row['aliases']]:
            canonical = key(name)
            if canonical in rows and rows[canonical] is not row:
                raise ValueError("Parser aliases collapse distinct evidence records")
            rows[canonical] = row

    def leaf(node):
        if node['op'] == 'specialized_experience':
            from jobsearch.evaluation.work_evidence import compare as compare_work
            return compare_work(node, evidence)
        if node['op'] in {'degree', 'credential', 'credits', 'unresolved', 'recognized_degree', 'recognized_credits'}:
            from jobsearch.evaluation.qualification_facts import compare as compare_fact
            return compare_fact(node, evidence)
        row = rows.get(key(node['skill']))
        status, explanation = 'unknown', 'No established evidence for this requirement.'
        transfers = [r for r in evidence['skills'] if key(node['skill']) in {key(v) for v in r['transfers_to']} and r['state'] == 'established']
        if row:
            if node['op'] == 'commercial_years':
                if row['state'] in {'none', 'no_meaningful_professional'} or row['commercial'] is False:
                    status, explanation = 'mismatch', 'Explicit absence of the required professional experience; no numeric duration invented.'
                elif row['state'] == 'established' and row['commercial'] is True:
                    years = row['approximate_years']
                    if years is not None:
                        status = 'supported' if years >= node['minimum'] else 'gap'
                        explanation = 'Reported approximate duration supports comparison; it is not a verified exact minimum.' if status == 'supported' else 'Numeric shortfall with relevant experience; hold, do not reject automatically.'
            elif node['op'] == 'expertise' and row['expertise'] is not None:
                status = 'supported' if row['expertise'] else 'mismatch'
                explanation = 'Explicit expertise assertion; depth and years do not imply expertise.'
            elif node['op'] == 'experience' and row['state'] == 'established' and row['commercial'] is True:
                status, explanation = 'supported', 'Reported professional experience supports this capability, not every job qualification.'
            elif node['op'] == 'experience' and row['state'] in {'none', 'no_meaningful_professional'}:
                status, explanation = 'mismatch', 'Applicant explicitly reports no meaningful experience for this capability.'
        if transfers and status != 'supported':
            status, explanation = 'adjacent', 'Explicit transferable evidence exists; it does not establish the exact requirement.'
        return dict(status=status, requirement=node, applicant_evidence=row, transferable_evidence=transfers, explanation=explanation)

    def visit(node):
        if node['op'] not in {'all', 'any'}:
            return leaf(node)
        children = [visit(c) for c in node['children']]
        states = [c['status'] for c in children]
        if node['op'] == 'all':
            state = ('mismatch' if 'mismatch' in states else 'unknown' if not states or 'unknown' in states
                     else 'adjacent' if 'adjacent' in states else 'gap' if 'gap' in states else 'supported')
        else:
            state = ('supported' if 'supported' in states else 'gap' if 'gap' in states else 'adjacent' if 'adjacent' in states
                     else 'mismatch' if states and all(s == 'mismatch' for s in states) else 'unknown')
        return dict(status=state, op=node['op'], children=children)
    return visit(tree)
