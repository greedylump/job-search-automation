"""Positive career relevance is distinct from mandatory qualification clearance."""
import re
from jobsearch.evaluation.parser_profiles import resolve_profile


def evaluate_signals(job, evidence, profile):
    from jobsearch.evaluation.qualification import compare
    profile = resolve_profile(profile)
    title = job.get('title') or ''
    results = []
    for signal in profile.get('capability_signals', []):
        match = re.search(signal['title_pattern'], title, re.I)
        if match:
            comparison = compare(dict(op='experience',skill=signal['skill']),evidence,profile)
            results.append(dict(name=signal['name'],skill=signal['skill'],status=comparison['status'],
                evidence=dict(field='title',start=match.start(),end=match.end(),text=match[0]),
                comparison=comparison))
    return dict(purpose='role_relevance_only_not_eligibility',signals=results,
                supported=any(r['status']=='supported' for r in results))
