"""Compose one shared basic requirement with alternative grades, fail closed on gaps."""
import re


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {'section', 'bridge'}:
        raise ValueError('Composition requires section and bridge')
    if any(not isinstance(v, str) or not v.strip() for v in config.values()):
        raise ValueError('Composition configuration must be nonblank')
    try:
        pattern = re.compile(config['bridge'], re.I)
    except re.error as exc:
        raise ValueError('Invalid composition bridge') from exc
    if pattern.groups or pattern.search('') is not None:
        raise ValueError('Composition bridge cannot capture or match empty text')


def extract(job, sections, paths, path_config, config):
    validate_config(config)
    text = job.get('description') or ''
    result = dict(version='qualification-composition-v1', complete=False, grades=[],
                  tree=dict(op='unresolved'), unparsed=[], blockers=[])
    candidates = [s for s in sections['sections'] if s['label'].casefold() == config['section'].casefold()]
    if len(candidates) != 1:
        result['blockers'].append('Expected exactly one composition section.')
        return result
    section = candidates[0]['evidence']
    local = [p for p in paths['paths'] if section['start'] <= p['evidence']['start'] < p['evidence']['end'] <= section['end']]
    basics = [p for p in local if p['kind'] == 'basic']
    grades = [p for p in local if p['kind'] == 'grade']
    if len(basics) != 1 or not grades or len({p['grade'] for p in grades}) != len(grades):
        result['blockers'].append('Basic/grade scope is missing, repeated, or ambiguous.')
        return result
    basic = basics[0]
    if basic['evidence']['end'] > grades[0]['heading']['start']:
        result['blockers'].append('Basic and grade scopes overlap.')
        return result
    bridge_start, bridge_end = basic['evidence']['end'], grades[0]['heading']['start']
    bridge = text[bridge_start:bridge_end]
    if re.fullmatch(config['bridge'], bridge.strip(), re.I) is None:
        result['blockers'].append('Basic-to-grade relationship is not fully recognized.')
        return result
    starts = list(re.finditer(path_config['basic_start'], section['text'], re.I))
    if len(starts) != 1:
        result['blockers'].append('Basic heading is ambiguous.')
        return result
    covered_start = section['start'] + starts[0].start()
    covered_end = grades[-1]['evidence']['end']
    # Cover only explicitly composed structure. Other sections and leading text
    # may contain exceptions or eligibility conditions and cannot be ignored.
    for item in sections['sections']:
        span = item['evidence']
        intervals = [(span['start'], span['end'])] if item is not candidates[0] else [
            (span['start'], covered_start), (covered_end, span['end'])]
        for start, end in intervals:
            if text[start:end].strip():
                result['unparsed'].append(dict(field='description',start=start,end=end,text=text[start:end]))
    result['grades'] = [dict(grade=p['grade'], tree=dict(op='all', children=[basic['tree'], p['tree']])) for p in grades]
    result['tree'] = dict(op='all', children=[basic['tree'], dict(op='any',children=[p['tree'] for p in grades])])
    result['bridge_evidence'] = dict(field='description',start=bridge_start,end=bridge_end,text=bridge)
    result['complete'] = not result['unparsed']
    if result['unparsed']:
        result['blockers'].append('Source text outside the composed requirements remains unresolved.')
    return result
