"""Conservative policy routing, not a qualification or application approval."""
from dataclasses import dataclass
import re

from jobsearch.evaluation.rules import normalized, _amount, PAY_PERIODS
from jobsearch.storage.policy_repository import validate_policy, validate_strategy

RULES_VERSION = "tier-policy-v1"


@dataclass(frozen=True)
class Result:
    decision: str
    reasons: list[dict]
    tier: str | None
    tailoring_level: str | None


def evaluate(context: dict) -> Result:
    """Replay using only the saved inputs. Unknown facts never become failures.

    Role examples are positive routing hints, not an exhaustive allowlist.
    A-D precedence chooses effort guidance, not an asserted probability of hire.
    """
    bundle, job = context["search_policy"], context["job"]
    policy, strategies = bundle["policy"], bundle["strategies"]
    validate_policy(policy)
    for strategy in strategies:
        validate_strategy(strategy)
    if len(strategies) != 4 or {s["tier"] for s in strategies} != set("ABCD"):
        raise ValueError("Evaluation requires all four strategy definitions")
    reasons = []

    def record(check, outcome, message, **evidence):
        reasons.append(dict(check=check, outcome=outcome, message=message, **evidence))

    arrangement = normalized(job.get("remote_type"))
    alternatives = policy["location"]["alternatives"]
    compatible = [r for r in alternatives if arrangement in r["arrangements"]]
    if arrangement not in {"remote", "hybrid", "onsite"}:
        record("work_arrangement", "review", "Work arrangement is unknown or unfamiliar.")
    elif not compatible:
        record("work_arrangement", "reject", "Known work arrangement matches no policy alternative.")
    else:
        record("work_arrangement", "keep", "Work arrangement matches a policy alternative; geography is checked separately.")
    # Job.location is free text, not a country/region or applicant eligibility fact.
    record("geography", "review", "Country, region, remote eligibility and any relocation need require confirmation; no geography or commute was inferred.",
           compatible_alternatives=compatible, relocation=policy["location"]["relocation"])

    employment = normalized(job.get("employment_type"))
    known_types = {"full_time", "part_time", "temporary", "w2_contract", "contract", "consulting", "c2c"}
    allowed = policy["employment_types"]
    if employment == "c2c" and "c2c" in policy["exclusions"]:
        record("employment", "reject", "Explicit C2C employment is excluded.")
    elif employment not in known_types:
        record("employment", "review", "Employment type is missing or unfamiliar.")
    elif employment in {"contract", "consulting"} and "c2c" in policy["exclusions"]:
        record("employment", "review", "Contract/consulting does not establish W-2 versus C2C terms.")
    elif allowed and employment not in allowed:
        record("employment", "reject", "Known employment type is outside the shared allowed types.")
    else:
        record("employment", "keep", "Employment type passes the configured shared constraint.")

    for exclusion in policy["exclusions"]:
        if exclusion == "c2c" and employment in {"c2c", "w2_contract"}:
            record(exclusion, "reject" if employment == "c2c" else "keep", "Explicit employment classification resolves the C2C check.")
        else:
            record(exclusion, "review", "Structured evidence is unavailable; review the saved description. Absence of a keyword is not proof that the exclusion is absent.")
    record("eligibility", "review", "Citizenship and reported credentials do not establish all job eligibility or mandatory qualifications; unlisted credentials are not assumed missing.")

    title = normalized(job.get("title"))
    candidates = []
    for strategy in sorted(strategies, key=lambda s: s["tier"]):
        if not strategy["enabled"]:
            continue
        matches = [role for role in strategy["definition"]["roles"]
                   if re.search(r"(?<!\w)" + re.escape(normalized(role)) + r"(?!\w)", title)]
        if matches:
            candidates.append(dict(tier=strategy["tier"], matched_roles=matches))
    selected = next((s for s in strategies if candidates and s["tier"] == candidates[0]["tier"]), None)
    record("tier_assignment", "review", "Provisional title routing uses A-D precedence among matching enabled strategies; it does not establish fit."
           if selected else "No enabled strategy title phrase matched; retain for manual tier review, without an automatic D fallback.",
           candidates=candidates, selected_tier=selected["tier"] if selected else None)
    definition = selected["definition"] if selected else {}
    record("hireability", "review", "No qualification, experience duration, or probability of hire inferred from title or reported skills.")
    record("career_value", "review", "Strategy guidance requires human judgment; no career-value score assigned.", guidance=definition.get("guidance"))
    low, high = job.get("salary_min"), job.get("salary_max")
    pay_known = (_amount(low) and _amount(high) and low <= high
                 and bool(re.fullmatch(r"[a-z]{3}", normalized(job.get("salary_currency"))))
                 and normalized(job.get("salary_period")) in PAY_PERIODS)
    record("income_value", "review", "Compensation is available but value requires strategy-specific judgment; no global floor or conversion applied."
           if pay_known else "Compensation is incomplete or inconsistent; no global floor, market rate, or conversion inferred.",
           compensation_guidance=definition.get("compensation_guidance"))
    record("application_friction", "review", "Application time and cost are unknown; a URL or tailoring level does not establish low effort. No platform interaction is authorized by this result.",
           max_application_minutes=definition.get("max_application_minutes"),
           tailoring=definition.get("tailoring"), avoid_aggressive_platforms=policy["automation"]["avoid_aggressive_platforms"])
    decision = "reject" if any(r["outcome"] == "reject" for r in reasons) else "review"
    return Result(decision, reasons, selected["tier"] if selected else None,
                  definition.get("tailoring"))
