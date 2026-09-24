"""Lossless section and clause extraction, without guessing logical scope.

Captured clauses are observations, not independently mandatory requirements.
An OR between clauses can apply to grades, degrees, or an entire experience path.
Until that scope is resolved the analysis cannot authorize a pass or rejection.
"""
import re


VERSION = 'qualification-sections-v1'


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {'ats_type', 'headings', 'include', 'clauses'}:
        raise ValueError('Qualification sections require ats_type, headings, include, clauses')
    if not isinstance(config['ats_type'], str) or not config['ats_type'].strip():
        raise ValueError('Qualification section source must be nonblank')
    for field in ('headings', 'include'):
        values = config[field]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError('Section headings must be nonempty string lists')
        if len({v.casefold() for v in values}) != len(values):
            raise ValueError('Duplicate section heading')
    if not set(config['include']) <= set(config['headings']):
        raise ValueError('Included sections must be configured headings')
    if not isinstance(config['clauses'], list) or not config['clauses']:
        raise ValueError('Clause definitions must be a nonempty list')
    names = set()
    for clause in config['clauses']:
        if not isinstance(clause, dict) or set(clause) != {'name', 'kind', 'pattern'}:
            raise ValueError('Clause definitions require name, kind, pattern')
        if any(not isinstance(v, str) or not v.strip() for v in clause.values()):
            raise ValueError('Clause values must be nonblank strings')
        if clause['name'] in names:
            raise ValueError('Duplicate clause name')
        names.add(clause['name'])
        try:
            pattern = re.compile(clause['pattern'], re.I)
        except re.error as exc:
            raise ValueError('Invalid qualification clause pattern') from exc
        if pattern.groups != len(pattern.groupindex) or pattern.search('') is not None:
            raise ValueError('Clause patterns require named captures only and cannot match empty text')


def extract(job, config):
    validate_config(config)
    text = job.get('description') or ''
    result = dict(version=VERSION, applicable=job.get('ats_type') == config['ats_type'],
                  complete=False, sections=[], unresolved=[])
    if not result['applicable']:
        return result

    def proof(start, end):
        return dict(field='description', start=start, end=end, text=text[start:end])

    # Only source-normalizer section labels at paragraph boundaries count.
    pattern = r'(?:\A|\n\n)(?P<label>' + '|'.join(re.escape(v) for v in config['headings']) + r'): '
    headings = list(re.finditer(pattern, text, re.I))
    included = {v.casefold() for v in config['include']}
    for index, heading in enumerate(headings):
        if heading['label'].casefold() not in included:
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[start:end]
        clauses = []
        for definition in config['clauses']:
            for match in re.finditer(definition['pattern'], body, re.I):
                if match.start() == match.end():
                    continue
                clauses.append(dict(kind=definition['kind'], pattern=definition['name'],
                    captures={k: v for k, v in match.groupdict().items() if v is not None},
                    evidence=proof(start + match.start(), start + match.end()),
                    scope_status='unresolved'))
        clauses.sort(key=lambda c: (c['evidence']['start'], c['evidence']['end'], c['pattern']))
        # Preserve gaps verbatim. Counting matches is not qualification coverage.
        remaining = []
        cursor = start
        for clause in clauses:
            span = clause['evidence']
            if span['start'] > cursor and text[cursor:span['start']].strip():
                remaining.append(proof(cursor, span['start']))
            cursor = max(cursor, span['end'])
        if cursor < end and text[cursor:end].strip():
            remaining.append(proof(cursor, end))
        result['sections'].append(dict(label=heading['label'], evidence=proof(start, end),
            clauses=clauses, unparsed=remaining, scope_status='unresolved'))
    result['unresolved'] = ['Qualification branch scope and mandatory status require resolution.']
    if not result['sections']:
        result['unresolved'].append('No configured qualification section found.')
    return result
