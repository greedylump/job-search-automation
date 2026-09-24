"""Explicit experience evidence and three-valued mandatory-requirement logic."""
import math
import re

from jobsearch.evaluation.rules import normalized

VERSION = "qualification-v2"
from jobsearch.evaluation.parser_profiles import resolve_profile


def skill_key(value, profile=None):
    key = normalized(value)
    return resolve_profile(profile)['aliases'].get(key, key)


def validate_evidence(value, profile=None):
    if value is None:
        return
    if isinstance(value, dict) and type(value.get('schema_version')) is int and value['schema_version'] in (2, 3, 4):
        from jobsearch.evaluation.rich_evidence import validate
        return validate(value)
    if not isinstance(value, dict) or set(value) != {"schema_version", "skills", "job_exclusions"}:
        raise ValueError("experience_evidence requires schema_version, skills, job_exclusions")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported experience evidence schema")
    if not isinstance(value["skills"], list) or not isinstance(value["job_exclusions"], list):
        raise ValueError("Evidence skills and job_exclusions must be lists")
    seen = set()
    for row in value["skills"]:
        fields = {"skill", "commercial_years_min", "commercial_years_max", "expertise", "source"}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Invalid experience skill fields")
        if any(not isinstance(row[k], str) or not row[k].strip() for k in ("skill", "source")):
            raise ValueError("Skill and evidence source must be nonblank")
        key = skill_key(row["skill"], profile)
        if key in seen:
            raise ValueError("Duplicate canonical skill evidence")
        seen.add(key)
        low, high = row["commercial_years_min"], row["commercial_years_max"]
        for number in (low, high):
            if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
                raise ValueError("Experience bounds must be finite nonnegative numbers or null")
        if low is not None and high is not None and low > high:
            raise ValueError("Experience bounds are inconsistent")
        if row["expertise"] is not None and type(row["expertise"]) is not bool:
            raise ValueError("expertise must be boolean or null")
    seen = set()
    for row in value["job_exclusions"]:
        if not isinstance(row, dict) or set(row) != {"source", "source_job_id", "reason"}:
            raise ValueError("Job exclusion requires source, source_job_id, reason")
        if any(not isinstance(v, str) or not v.strip() for v in row.values()):
            raise ValueError("Exclusion fields must be nonblank strings")
        key = (row["source"], row["source_job_id"])
        if key in seen:
            raise ValueError("Duplicate job exclusion")
        seen.add(key)


def compare(tree, evidence, profile=None):
    """AND fails on one mismatch; OR fails only when all alternatives fail."""
    validate_evidence(evidence, profile)
    if evidence and evidence['schema_version'] in (2, 3, 4):
        from jobsearch.evaluation.rich_evidence import compare as compare_rich
        return compare_rich(tree, evidence, profile)
    rows = {skill_key(r["skill"], profile): r for r in (evidence or {}).get("skills", [])}

    def visit(node):
        if node["op"] in {"all", "any"}:
            children = [visit(child) for child in node["children"]]
            states = [c["status"] for c in children]
            if node["op"] == "all":
                state = "mismatch" if "mismatch" in states else "supported" if states and all(s == "supported" for s in states) else "unknown"
            else:
                state = "supported" if "supported" in states else "mismatch" if states and all(s == "mismatch" for s in states) else "unknown"
            return dict(status=state, op=node["op"], children=children)
        if node['op'] == 'specialized_experience':
            from jobsearch.evaluation.work_evidence import compare as compare_work
            return compare_work(node, evidence)
        if node['op'] in {'degree', 'credential', 'credits', 'unresolved', 'recognized_degree', 'recognized_credits'}:
            from jobsearch.evaluation.qualification_facts import compare as compare_fact
            return compare_fact(node, evidence)
        row = rows.get(skill_key(node["skill"], profile))
        state = "unknown"
        if row and node["op"] == "commercial_years":
            low, high, needed = row["commercial_years_min"], row["commercial_years_max"], node["minimum"]
            if low is not None and low >= needed:
                state = "supported"
            elif high is not None and high < needed:
                state = "mismatch"
        elif row and node["op"] == "expertise" and row["expertise"] is not None:
            state = "supported" if row["expertise"] else "mismatch"
        return dict(status=state, requirement=node, applicant_evidence=row)

    return visit(tree)


def extract_requirements(job, profile=None):
    profile = resolve_profile(profile)
    result = _extract_legacy_requirements(job, profile)
    if profile['schema_version'] in (3, 4, 5, 6):
        from jobsearch.evaluation.qualification_sections import extract
        analysis = extract(job, profile['qualification_sections'])
        result['section_analysis'] = analysis
        result['version'] = 'qualification-v3'
        if analysis['applicable']:
            # Do not let a locally parsed Requirements block override alternatives
            # in Qualifications/Education that the old grammar never considered.
            result['complete'] = False
            result['ambiguous'] = True
            result['unresolved'].extend(analysis['unresolved'])
        if profile['schema_version'] in (4, 5, 6) and analysis['applicable']:
            from jobsearch.evaluation.qualification_paths import extract
            result['path_analysis'] = extract(job, analysis, profile['qualification_paths'])
            result['version'] = 'qualification-v4'
            if profile['schema_version'] in (5, 6):
                from jobsearch.evaluation.qualification_composition import extract as compose
                composition = compose(job, analysis, result['path_analysis'], profile['qualification_paths'],
                                      profile['qualification_composition'])
                if profile['schema_version'] == 6:
                    from jobsearch.evaluation.source_conditions import resolve
                    composition = resolve(composition, profile['qualification_conditions'])
                result['composition'] = composition
                result['tree'] = composition['tree']
                result['complete'] = composition['complete']
                result['ambiguous'] = not composition['complete']
                result['unresolved'] = composition['blockers']
                result['version'] = 'qualification-v6' if profile['schema_version'] == 6 else 'qualification-v5'
    return result


def _extract_legacy_requirements(job, profile=None):
    """Parse a small, explicit grammar; unparsed coverage prevents promotion.

    The commercial-experience block supports comma/AND clauses and OR branches.
    Do not search arbitrary prose or unrelated-role advertising for skill hits.
    """
    profile = resolve_profile(profile)
    patterns = profile["patterns"]
    text = job.get("description") or ""
    headings = list(re.finditer(patterns['section_heading'], text, re.I))
    if not headings:
        return dict(version=VERSION, parser_profile=profile, tree={"op": "all", "children": []}, complete=False,
                    evidence=[], unresolved=["No supported requirements section."])
    heading = headings[0]
    start = heading.end()
    end_match = re.search(patterns['section_end'], text[start:], re.I)
    end = start + end_match.start() if end_match else len(text)
    body = text[start:end]
    nodes, spans, unresolved = [], [], []

    def proof(begin, finish):
        spans.append(dict(field="description", start=start + begin, end=start + finish,
                          text=text[start + begin:start + finish]))

    # Retain all unparsed content; only a fully supported section can pass.
    consumed = []
    commercial = re.search(patterns['experience_heading'], body, re.I)
    if commercial and re.search(patterns['negation_prefix'], body[:commercial.start()], re.I):
        unresolved.append("Negated commercial-experience block is not a mandatory requirement.")
        commercial = None
    if commercial:
        stop = re.search(patterns['experience_end'], body[commercial.end():], re.I)
        finish = commercial.end() + stop.start() if stop else len(body)
        block = body[commercial.end():finish].strip()
        alternatives = re.split(patterns['or_separator'], block, flags=re.I)
        branches = []
        valid = True
        for alternative in alternatives:
            clauses = re.split(patterns['and_separator'], alternative, flags=re.I)
            leaves = []
            for clause in clauses:
                match = re.fullmatch(patterns['years_clause'], clause, re.I)
                if not match:
                    valid = False
                    break
                leaves.append(dict(op="commercial_years", skill=skill_key(match[1], profile), minimum=float(match[2])))
            branches.append(dict(op="all", children=leaves))
        if valid and branches:
            nodes.append(dict(op="any", children=branches))
            consumed.append((commercial.start(), finish))
            proof(commercial.start(), finish)
        else:
            unresolved.append("Commercial experience block has unsupported or ambiguous syntax.")
    # Expertise sentences are mandatory only in this explicitly labeled section.
    for match in re.finditer(patterns['expertise_clause'], body, re.I):
        if re.search(patterns['negation_prefix'], body[:match.start()], re.I):
            unresolved.append("Negated expertise statement is not a mandatory requirement.")
            continue
        names = re.split(patterns['skill_separator'], match[1], flags=re.I)
        if all(re.fullmatch(patterns['skill_name'], name.strip()) for name in names) and not re.search(patterns['or_word'], match[1], re.I):
            nodes.extend(dict(op="expertise", skill=skill_key(name, profile)) for name in names)
            consumed.append((match.start(), match.end()))
            proof(match.start(), match.end())
    remaining = list(body)
    for begin, finish in consumed:
        remaining[begin:finish] = " " * (finish - begin)
    if re.sub(patterns['formatting'], "", "".join(remaining)):
        unresolved.append("Unparsed requirements remain; do not assume qualification coverage is complete.")
    if not nodes:
        unresolved.append("No mandatory experience clauses recognized.")
    # Ambiguous alternatives, waivers, and multiple requirement sections must
    # not turn partial clauses into confident mismatch decisions.
    ambiguous = bool(re.search(patterns['ambiguity'], body, re.I)) or len(headings) > 1
    return dict(version=VERSION, parser_profile=profile, tree=dict(op="all", children=nodes),
                complete=bool(nodes) and not unresolved and not ambiguous,
                evidence=spans, unresolved=unresolved + (["Requirement scope/alternatives are ambiguous."] if ambiguous else []),
                ambiguous=ambiguous)


def assess(job, evidence, requirements, *, eligibility=None):
    profile = requirements.get("parser_profile")
    validate_evidence(evidence, profile)
    for exclusion in (evidence or {}).get("job_exclusions", []):
        if (job.get("source"), job.get("source_job_id")) == (exclusion["source"], exclusion["source_job_id"]):
            return dict(status="mismatch", reason="Applicant explicitly excluded this job.", exclusion=exclusion)
    comparison = compare(requirements["tree"], evidence, profile)
    state = comparison["status"]
    if requirements.get("ambiguous") or (state == "supported" and not requirements["complete"]):
        state = "unknown"
    result = dict(status=state, comparison=comparison, extraction=requirements,
                reason={"supported": "Recorded evidence supports all recognized requirements with complete parser coverage.",
                        "mismatch": "Recorded evidence conflicts with a mandatory requirement in every applicable alternative.",
                        "gap": "Relevant experience with a numeric shortfall; retain internally without automatic rejection.",
                        "adjacent": "Transferable experience remains viable but does not establish the exact requirement.",
                        "unknown": "Required evidence or requirement coverage is incomplete; hold outside the prospective queue."}[state])
    if 'path_analysis' in requirements:
        result['path_assessments'] = [dict(kind=p['kind'], grade=p.get('grade'), evidence=p['evidence'],
            comparison=compare(p['tree'], evidence, profile)) for p in requirements['path_analysis']['paths']]
    if 'composition' in requirements:
        composition = requirements['composition']
        result['overall_qualification'] = dict(status=state, coverage_complete=composition['complete'],
            blockers=composition['blockers'], unparsed=composition['unparsed'],
            grades=[dict(grade=p['grade'], comparison=compare(p['tree'], evidence, profile)) for p in composition['grades']])
    if 'conditions' in requirements.get('composition', {}):
        from jobsearch.evaluation.source_conditions import assess as assess_conditions
        result['source_conditions'] = assess_conditions(requirements['composition']['conditions'], eligibility)
    if profile and profile.get('schema_version') in (2, 3, 4, 5, 6):
        from jobsearch.evaluation.role_signals import evaluate_signals
        result['role_relevance'] = evaluate_signals(job, evidence, profile)
    return result


HARD_CHECKS = {"availability", "geography", "work_arrangement", "employment", "eligibility", "citizenship",
               "c2c", "active_clearance_required", "clearance_core_requirement",
               "significant_physical_labor", "known_missing_mandatory_credentials"}


def queue_state(assessment, reasons):
    if assessment["status"] == "mismatch" or any(r["outcome"] == "reject" for r in reasons):
        return "do_not_pursue"
    if any(c['kind']=='citizenship' and c['status']!='supported' for c in assessment.get('source_conditions', [])):
        return 'unresolved'
    if assessment["status"] != "supported" or any(r["outcome"] == "review" and r["check"] in HARD_CHECKS for r in reasons):
        return "unresolved"
    return "plausible"
