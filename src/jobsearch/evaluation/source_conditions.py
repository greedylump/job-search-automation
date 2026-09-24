"""Resolve configured whole source blocks into separate qualification and application conditions."""
from copy import deepcopy
import re


def validate_config(config):
    if not isinstance(config,list) or not config: raise ValueError('Condition rules must be a nonempty list')
    for rule in config:
        if not isinstance(rule,dict) or rule.get('kind') not in ('qualification_guidance','foreign_education'):
            raise ValueError('Unsupported source condition kind')
        fields = {'kind','pattern','country'}
        if rule['kind']=='qualification_guidance': fields |= {'citizenship_values','application_obligations'}
        if set(rule)!=fields: raise ValueError('Invalid condition rule fields')
        if not isinstance(rule['country'],str) or not re.fullmatch('[A-Z]{2}',rule['country']):
            raise ValueError('Condition country must be an uppercase two-letter code')
        if not isinstance(rule['pattern'],str): raise ValueError('Condition pattern must be text')
        try: pattern=re.compile(rule['pattern'],re.I)
        except re.error as exc: raise ValueError('Invalid condition pattern') from exc
        if pattern.groups or pattern.search('') is not None: raise ValueError('Condition patterns cannot capture or match empty text')
        if rule['kind']=='qualification_guidance':
            for name in ('citizenship_values','application_obligations'):
                if not isinstance(rule[name],list) or not rule[name] or any(not isinstance(v,str) or not v.strip() for v in rule[name]):
                    raise ValueError('Condition values must be nonempty string lists')


def resolve(composition, rules):
    validate_config(rules)
    result=deepcopy(composition)
    result['conditions']=[]
    if not result['grades']:
        return result
    remaining=[]
    for span in result['unparsed']:
        matches=[r for r in rules if re.fullmatch(r['pattern'],span['text'].strip(),re.I)]
        if len(matches)!=1:
            remaining.append(span)
        else:
            result['conditions'].append(dict(rule=deepcopy(matches[0]),evidence=span))
    countries={c['rule']['country'] for c in result['conditions'] if c['rule']['kind']=='foreign_education'}
    if len(countries)>1:
        result['complete']=False
        result['blockers']=['Conflicting education-recognition scopes.']
        return result
    if countries:
        country=next(iter(countries))
        def guarded(node):
            if node['op'] in ('degree','credits'):
                node['op']='recognized_'+node['op']; node['country']=country
            for child in node.get('children',[]): guarded(child)
        guarded(result['tree'])
        for grade in result['grades']: guarded(grade['tree'])
    result['unparsed']=remaining
    result['complete']=not remaining
    result['blockers']=['Source text outside the composed requirements remains unresolved.'] if remaining else []
    result['version']='qualification-conditions-v1'
    return result


def assess(conditions, eligibility):
    results=[]
    values=(eligibility or {}).get('citizenships',[])
    for condition in conditions:
        rule=condition['rule']
        if rule['kind']=='qualification_guidance':
            accepted={v.casefold() for v in rule['citizenship_values']}
            matched=[v for v in values if v.casefold() in accepted]
            results.append(dict(kind='citizenship',status='supported' if matched else 'unknown',
                country=rule['country'],applicant_evidence=matched,evidence=condition['evidence'],
                reason='Positive citizenship assertions only; other citizenships or an empty list do not prove absence.'))
            results.append(dict(kind='application_obligations',items=rule['application_obligations'],
                status='preparation_required',evidence=condition['evidence'],
                reason='Resume evidence and education-path transcripts must be prepared; possession or submission is not inferred.'))
        else:
            results.append(dict(kind='foreign_education',country=rule['country'],status='applied_to_education_branches',
                                evidence=condition['evidence']))
    return results
