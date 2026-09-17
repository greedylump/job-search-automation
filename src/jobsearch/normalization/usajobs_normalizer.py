"""Map public announcements; telework eligibility is not evidence of remote work."""
import math
from urllib.parse import urlsplit
from jobsearch.normalization.json_normalizer import JsonJobNormalizer
from jobsearch.normalization.remotive_normalizer import _DescriptionParser, _text


def mapping(value):
    return value if isinstance(value, dict) else {}


def first(value):
    return mapping(value[0]) if isinstance(value, list) and value else {}


def amount(value):
    try:
        number = float(value) if not isinstance(value, bool) else -1
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def safe_url(value):
    try:
        parsed = urlsplit(value) if isinstance(value, str) else None
        return value if parsed and parsed.scheme == 'https' and parsed.hostname and not parsed.username else None
    except ValueError:
        return None


def normalize(payload):
    descriptor = mapping(payload.get('MatchedObjectDescriptor'))
    details = mapping(mapping(descriptor.get('UserArea')).get('Details'))
    identifier = payload.get('MatchedObjectId')
    if type(identifier) not in (int, str) or not str(identifier).strip():
        identifier = None
    remuneration = first(descriptor.get('PositionRemuneration'))
    period = {'PA': 'annual', 'PH': 'hourly', 'PM': 'monthly', 'PW': 'weekly'}.get(remuneration.get('RateIntervalCode'))
    parts = []
    for label, value in [('Summary', details.get('JobSummary')),
                         ('Qualifications', descriptor.get('QualificationSummary')),
                         ('Duties', details.get('MajorDuties')),
                         ('Requirements', details.get('Requirements')),
                         ('Education', details.get('Education')),
                         ('Who may apply', mapping(details.get('WhoMayApply')).get('Name')),
                         ('Application closes', descriptor.get('ApplicationCloseDate'))]:
        if isinstance(value, list):
            value = '\n'.join(v for v in value if isinstance(v, str))
        if isinstance(value, str) and value.strip():
            parser = _DescriptionParser()
            parser.feed(value)
            parts.append(label + ': ' + ' '.join(' '.join(parser.parts).split()))
    apply = descriptor.get('ApplyURI')
    if isinstance(apply, list):
        apply = next((v for v in apply if safe_url(v)), None)
    remote = details.get('RemoteIndicator')
    return JsonJobNormalizer.normalize(dict(
        source_job_id=identifier, title=_text(descriptor.get('PositionTitle')),
        company=_text(descriptor.get('OrganizationName')),
        location=_text(descriptor.get('PositionLocationDisplay')),
        remote_type='remote' if remote is True or remote == 'True' else None,
        employment_type=_text(first(descriptor.get('PositionSchedule')).get('Name')),
        salary_min=amount(remuneration.get('MinimumRange')), salary_max=amount(remuneration.get('MaximumRange')),
        salary_period=period, salary_currency=None,
        description='\n\n'.join(parts) or None, job_url=safe_url(descriptor.get('PositionURI')),
        apply_url=safe_url(apply), posted_at=_text(descriptor.get('PublicationStartDate')),
        ats_type='usajobs'), source='usajobs')
