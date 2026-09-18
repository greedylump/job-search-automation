"""Validated policy configuration. Complete replacements, with revision checks."""
from copy import deepcopy
from sqlalchemy import select
from jobsearch.models import Applicant, SearchPolicy, TierStrategy
from jobsearch.storage.source_repository import utcnow


def exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f'{label} requires exactly: {", ".join(fields)}')


def strings(value, label):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f'{label} must be a list of nonblank strings')


def validate_policy(value):
    exact(value, ('schema_version','objective','location','employment_types','exclusions',
                  'eligibility','unknown_handling','compensation','scoring_dimensions','automation'), 'Policy')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Only policy schema_version 1 is supported')
    if not isinstance(value['objective'], str) or not value['objective'].strip():
        raise ValueError('objective must be nonblank')
    exact(value['location'], ('home_postal_code','alternatives','relocation'), 'Location')
    location = value['location']
    if location['home_postal_code'] is not None and not isinstance(location['home_postal_code'], str):
        raise ValueError('home_postal_code must be text or null')
    if location['relocation'] not in ('review', 'allowed', 'excluded'):
        raise ValueError('Invalid relocation policy')
    if not isinstance(location['alternatives'], list) or not location['alternatives']:
        raise ValueError('Provide at least one alternative location rule')
    for rule in location['alternatives']:
        exact(rule, ('arrangements','country','region'), 'Location alternative')
        strings(rule['arrangements'], 'arrangements')
        if not rule['arrangements'] or set(rule['arrangements']) - {'remote','hybrid','onsite'}:
            raise ValueError('Invalid work arrangements')
        if not isinstance(rule['country'], str) or not rule['country'].strip():
            raise ValueError('country is required')
        if rule['region'] is not None and (not isinstance(rule['region'], str) or not rule['region'].strip()):
            raise ValueError('region must be nonblank text or null')
    strings(value['employment_types'], 'employment_types')
    if set(value['employment_types']) - {'full_time','w2_contract','temporary','part_time','contract','consulting'}:
        raise ValueError('Unsupported employment type')
    strings(value['exclusions'], 'exclusions')
    if set(value['exclusions']) - {'c2c','active_clearance_required','clearance_core_requirement',
                                  'significant_physical_labor','known_missing_mandatory_credentials'}:
        raise ValueError('Unsupported exclusion')
    exact(value['eligibility'], ('citizenships','known_credentials','credentials_complete'), 'Eligibility')
    strings(value['eligibility']['citizenships'], 'citizenships')
    strings(value['eligibility']['known_credentials'], 'known_credentials')
    if type(value['eligibility']['credentials_complete']) is not bool:
        raise ValueError('credentials_complete must be boolean')
    if value['unknown_handling'] != 'review' or value['compensation'] != 'per_strategy_no_global_floor':
        raise ValueError('Schema 1 requires review for unknowns and strategy-based compensation')
    if value['scoring_dimensions'] != ['hireability','career_value','income_value','application_friction']:
        raise ValueError('Keep the four scoring dimensions separate')
    exact(value['automation'], ('avoid_aggressive_platforms','allow_fabrication'), 'Automation')
    strings(value['automation']['avoid_aggressive_platforms'], 'avoid_aggressive_platforms')
    if value['automation']['allow_fabrication'] is not False:
        raise ValueError('Fabrication cannot be enabled')


def validate_strategy(value):
    exact(value, ('tier','name','enabled','definition'), 'Strategy')
    if value['tier'] not in ('A','B','C','D') or type(value['enabled']) is not bool:
        raise ValueError('Strategy requires tier A-D and boolean enabled')
    if not isinstance(value['name'], str) or not 1 <= len(value['name'].strip()) <= 128:
        raise ValueError('Strategy name must contain 1–128 characters')
    definition = value['definition']
    exact(definition, ('roles','guidance','tailoring','compensation_guidance','max_application_minutes'), 'Strategy definition')
    strings(definition['roles'], 'roles')
    for field in ('guidance','compensation_guidance'):
        if not isinstance(definition[field], str) or not definition[field].strip():
            raise ValueError(f'{field} must be nonblank')
    if definition['tailoring'] not in ('deep','light','minimal'):
        raise ValueError('Invalid tailoring level')
    minutes = definition['max_application_minutes']
    if minutes is not None and (type(minutes) is not int or minutes <= 0):
        raise ValueError('Application minutes must be a positive integer or null')


class PolicyRepository:
    def __init__(self, session):
        self.session = session

    def view(self, applicant_id):
        if type(applicant_id) is not int or applicant_id < 1:
            raise ValueError('applicant_id must be positive')
        policy = self.session.get(SearchPolicy, applicant_id)
        if policy is None:
            raise ValueError('No search policy for that applicant')
        rows = self.session.scalars(select(TierStrategy).where(TierStrategy.applicant_id == applicant_id).order_by(TierStrategy.tier))
        return dict(applicant_id=applicant_id, revision=policy.revision, policy=deepcopy(policy.definition),
            strategies=[dict(tier=r.tier, name=r.name, enabled=r.enabled, definition=deepcopy(r.definition)) for r in rows])

    def save(self, applicant_id, policy, strategies, expected_revision=None):
        validate_policy(policy)
        if not isinstance(strategies, list) or len(strategies) != 4:
            raise ValueError('Provide exactly four strategies, A through D')
        for strategy in strategies:
            validate_strategy(strategy)
        if {s['tier'] for s in strategies} != set('ABCD'):
            raise ValueError('Each tier A-D must occur exactly once')
        if type(applicant_id) is not int or applicant_id < 1 or self.session.get(Applicant, applicant_id) is None:
            raise ValueError('Applicant does not exist')
        current = self.session.get(SearchPolicy, applicant_id)
        if current:
            if type(expected_revision) is not int or expected_revision != current.revision:
                raise ValueError('Policy revision conflict; read the latest revision before editing')
            before = self.view(applicant_id)
            if before['policy'] == policy and before['strategies'] == sorted(strategies, key=lambda s: s['tier']):
                return current
            current.revision += 1
            current.definition = deepcopy(policy)
            current.updated_at = utcnow()
        else:
            if expected_revision not in (None, 0):
                raise ValueError('New policy must use revision 0 or omit it')
            current = SearchPolicy(applicant_id=applicant_id, revision=1, definition=deepcopy(policy),
                                   created_at=utcnow(), updated_at=utcnow())
            self.session.add(current)
            self.session.flush()
        for strategy in strategies:
            row = self.session.scalar(select(TierStrategy).where(TierStrategy.applicant_id == applicant_id,
                                                                TierStrategy.tier == strategy['tier']))
            if row is None:
                row = TierStrategy(applicant_id=applicant_id, tier=strategy['tier'])
                self.session.add(row)
            row.name, row.enabled = strategy['name'], strategy['enabled']
            row.definition, row.updated_at = deepcopy(strategy['definition']), utcnow()
        self.session.flush()
        return current
