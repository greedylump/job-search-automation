"""Validated, explicit parser conventions supplied by trusted configuration."""
from copy import deepcopy
import json
from pathlib import Path
import re

from jobsearch.evaluation.parser_defaults import DEFAULT_PROFILE
from jobsearch.evaluation.rules import normalized


def resolve_profile(profile=None):
    profile = deepcopy(DEFAULT_PROFILE if profile is None else profile)
    fields = {"schema_version", "name", "revision", "aliases", "patterns"}
    if isinstance(profile, dict) and profile.get('schema_version') in (2, 3, 4, 5, 6):
        fields.add('capability_signals')
    if isinstance(profile, dict) and profile.get('schema_version') in (3, 4, 5, 6):
        fields.add('qualification_sections')
    if isinstance(profile, dict) and profile.get('schema_version') in (4, 5, 6):
        fields.add('qualification_paths')
    if isinstance(profile, dict) and profile.get('schema_version') in (5, 6):
        fields.add('qualification_composition')
    if isinstance(profile, dict) and profile.get('schema_version') == 6:
        fields.add('qualification_conditions')
    if not isinstance(profile, dict) or set(profile) != fields:
        raise ValueError("Parser profile requires schema_version, name, revision, aliases, patterns")
    if type(profile["schema_version"]) is not int or profile["schema_version"] not in (1, 2, 3, 4, 5, 6):
        raise ValueError("Unsupported parser profile schema")
    if type(profile["revision"]) is not int or profile["revision"] < 1:
        raise ValueError("Parser profile revision must be positive")
    if not isinstance(profile["name"], str) or not profile["name"].strip():
        raise ValueError("Parser profile name must be nonblank")
    aliases = profile["aliases"]
    if not isinstance(aliases, dict):
        raise ValueError("aliases must be a mapping")
    for key, value in aliases.items():
        if not isinstance(key, str) or not isinstance(value, str) or not key or not value or key != normalized(key) or value != normalized(value):
            raise ValueError("Aliases must be nonblank canonical lowercase/whitespace-normalized strings")
        if value in aliases and aliases[value] != value:
            raise ValueError("Alias chains and cycles are not supported; map directly to canonical names")
    patterns = profile["patterns"]
    if profile['schema_version'] >= 2:
        if not isinstance(profile['capability_signals'], list):
            raise ValueError('capability_signals must be a list')
        for signal in profile['capability_signals']:
            if not isinstance(signal, dict) or set(signal) != {'name','skill','title_pattern'}:
                raise ValueError('Capability signals require name, skill, title_pattern')
            if any(not isinstance(v,str) or not v.strip() for v in signal.values()):
                raise ValueError('Capability signals must contain nonblank strings')
            try:
                pattern = re.compile(signal['title_pattern'], re.I)
            except re.error as exc:
                raise ValueError('Invalid capability title pattern') from exc
            if pattern.groups or pattern.search('') is not None:
                raise ValueError('Capability patterns cannot capture or match empty text')
    if not isinstance(patterns, dict) or set(patterns) != set(DEFAULT_PROFILE["patterns"]):
        raise ValueError("Parser profile must supply all grammar patterns")
    for name, pattern in patterns.items():
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("Parser patterns must be nonempty strings")
        try:
            compiled = re.compile(pattern, re.I)
        except re.error as exc:
            raise ValueError(f"Invalid parser pattern: {name}") from exc
        expected = 2 if name == "years_clause" else 1 if name == "expertise_clause" else 0
        if compiled.groups != expected:
            raise ValueError(f"{name} requires {expected} capture groups")
        if compiled.search("") is not None:
            raise ValueError(f"{name} must not match empty text")
    if profile['schema_version'] in (3, 4, 5, 6):
        from jobsearch.evaluation.qualification_sections import validate_config
        validate_config(profile['qualification_sections'])
    if profile['schema_version'] in (4, 5, 6):
        from jobsearch.evaluation.qualification_paths import validate_config
        validate_config(profile['qualification_paths'])
    if profile['schema_version'] in (5, 6):
        from jobsearch.evaluation.qualification_composition import validate_config
        validate_config(profile['qualification_composition'])
    if profile['schema_version'] == 6:
        from jobsearch.evaluation.source_conditions import validate_config
        validate_config(profile['qualification_conditions'])
    return profile


def load_profile(path):
    return resolve_profile(json.loads(Path(path).read_text(encoding="utf-8")))
