"""Resolve explicit local alternatives without merging grades or inferring scope."""
from copy import deepcopy
import math
import re


def validate_config(config):
    patterns = {'basic_start', 'basic_end', 'grade_heading', 'branch_separator', 'wrapper', 'local_or'}
    if not isinstance(config, dict) or set(config) != patterns | {'sections', 'leaf_rules'}:
        raise ValueError('Invalid qualification path configuration')
    if not isinstance(config['sections'], list) or not config['sections'] or any(not isinstance(v, str) or not v.strip() for v in config['sections']):
        raise ValueError('Path sections must be nonblank names')
    for name in patterns:
        if not isinstance(config[name], str) or not config[name]:
            raise ValueError('Path patterns must be nonblank')
        try:
            pattern = re.compile(config[name], re.I)
        except re.error as exc:
            raise ValueError('Invalid path pattern') from exc
        expected = {'grade'} if name == 'grade_heading' else set()
        if set(pattern.groupindex) != expected or pattern.groups != len(expected) or pattern.search('') is not None:
            raise ValueError('Path pattern captures or empty matches are invalid')
    if not isinstance(config['leaf_rules'], list) or not config['leaf_rules']:
        raise ValueError('leaf_rules must be a nonempty list')
    for rule in config['leaf_rules']:
        if not isinstance(rule, dict) or set(rule) != {'pattern', 'requirement'} or not isinstance(rule['pattern'], str):
            raise ValueError('Leaf rules require pattern and requirement')
        try:
            pattern = re.compile(rule['pattern'], re.I)
        except re.error as exc:
            raise ValueError('Invalid leaf pattern') from exc
        if pattern.groups != len(pattern.groupindex) or pattern.search('') is not None:
            raise ValueError('Leaf patterns require named captures only and cannot match empty text')
        node = rule['requirement']
        shapes = {'degree': {'op', 'levels', 'field'}, 'credential': {'op', 'name', 'current', 'by_examination'},
                  'credits': {'op', 'field', 'minimum'},
                  'specialized_experience': {'op', 'activities', 'minimum_months', 'grade_system', 'grade'}}
        if not isinstance(node, dict) or not isinstance(node.get('op'), str) or node['op'] not in shapes or set(node) != shapes[node['op']]:
            raise ValueError('Invalid typed requirement template')
        def string(value):
            if not isinstance(value, str) or not value.strip() or (value.startswith('$') and value[1:] not in pattern.groupindex):
                raise ValueError('Template strings must be nonblank values or named captures')
        if node['op'] == 'degree':
            if not isinstance(node['levels'], list) or not node['levels']:
                raise ValueError('Degree levels must be nonempty')
            for level in node['levels']: string(level)
        if node['op'] == 'credential':
            for key in ('current', 'by_examination'):
                if type(node[key]) is not bool: raise ValueError('Credential conditions must be boolean')
        if node['op'] == 'credits':
            value = node['minimum']
            if isinstance(value, str): string(value)
            elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('Credit minimum must be a number or capture')
        if node['op'] == 'specialized_experience':
            if not isinstance(node['activities'], list) or not node['activities']:
                raise ValueError('Specialized experience requires activities')
            for activity in node['activities']: string(activity)
            string(node['grade_system']); string(node['grade'])
            months = node['minimum_months']
            if type(months) not in (float, int) or not math.isfinite(months) or months <= 0:
                raise ValueError('Specialized experience duration must be a positive numeric month count')
        else:
            string(node['name'] if node['op'] == 'credential' else node['field'])


def extract(job, sections, config):
    validate_config(config)
    text = job.get('description') or ''

    def proof(start, end):
        return dict(field='description', start=start, end=end, text=text[start:end])

    def parse(start, end, depth=0):
        body = text[start:end]
        span = proof(start, end)
        if depth > 8:
            return dict(op='unresolved', evidence=span, reason='Alternative nesting limit')
        # Separators are explicit configured scope conventions, never arbitrary ORs.
        for key in ('branch_separator', 'local_or'):
            matches = list(re.finditer(config[key], body, re.I))
            if matches:
                children = []
                cursor = start
                for match in matches:
                    children.append(parse(cursor, start + match.start(), depth + 1))
                    cursor = start + match.end()
                children.append(parse(cursor, end, depth + 1))
                return dict(op='any', children=children, evidence=span,
                            connectors=[proof(start + m.start(), start + m.end()) for m in matches])
        # A configured structural wrapper is not itself qualification evidence.
        content = re.sub(config['wrapper'], '', body.strip(), count=1, flags=re.I).strip()
        candidates = []
        for rule in config['leaf_rules']:
            match = re.fullmatch(rule['pattern'], content, re.I)
            if match is None:
                continue
            node = deepcopy(rule['requirement'])
            def substitute(value):
                if isinstance(value, str) and value.startswith('$'):
                    return match.group(value[1:])
                if isinstance(value, list): return [substitute(v) for v in value]
                return value
            node = {k: substitute(v) for k, v in node.items()}
            if any(v is None for v in node.values()):
                continue
            if node['op'] == 'credits':
                try: node['minimum'] = float(node['minimum'])
                except (TypeError, ValueError): continue
                if not math.isfinite(node['minimum']) or node['minimum'] < 0: continue
            node['evidence'] = span
            candidates.append(node)
        if len(candidates) == 1:
            return candidates[0]
        return dict(op='unresolved', evidence=span, reason='Unsupported or ambiguous complete branch')

    paths = []
    for section in sections['sections']:
        if section['label'].casefold() not in {s.casefold() for s in config['sections']}:
            continue
        origin = section['evidence']['start']
        body = section['evidence']['text']
        basics = list(re.finditer(config['basic_start'], body, re.I))
        if len(basics) == 1:
            finish = re.search(config['basic_end'], body[basics[0].end():], re.I)
            if finish:
                start = origin + basics[0].end()
                end = start + finish.start()
                paths.append(dict(kind='basic', evidence=proof(start, end), tree=parse(start, end)))
        grades = list(re.finditer(config['grade_heading'], body, re.I))
        for index, heading in enumerate(grades):
            start = origin + heading.end()
            end = origin + (grades[index + 1].start() if index + 1 < len(grades) else len(body))
            paths.append(dict(kind='grade', grade=heading['grade'], heading=proof(origin + heading.start(), start),
                              evidence=proof(start, end), tree=parse(start, end)))
    return dict(version='qualification-paths-v1', paths=paths, complete=False,
        unresolved=['Local paths only: cross-section scope, specialized experience, and overall eligibility remain unresolved.'])
