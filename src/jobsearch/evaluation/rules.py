from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


RULES_VERSION = "preferences-v1"
PAY_PERIODS = {"hourly", "weekly", "monthly", "annual"}


def normalized(value: Any) -> str:
    """Case-fold and collapse whitespace, without geographic or synonym inference."""
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


@dataclass(frozen=True)
class Result:
    decision: str
    reasons: list[dict[str, str]]


def _ambiguous_location(value: str) -> bool:
    return (
        not value
        or bool(re.search(r"\b(remote|hybrid|onsite|anywhere|worldwide|multiple|various|tbd|unknown)\b", value))
        or any(separator in value for separator in (";", "|", "/", " or "))
    )


def _amount(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def evaluate(preferences: dict, job: dict) -> Result:
    """Evaluate every configured check; rejection wins over uncertainty."""
    reasons = []

    def record(check: str, outcome: str, message: str) -> None:
        reasons.append({"check": check, "outcome": outcome, "message": message})

    remote = normalized(preferences.get("remote_preference"))
    if remote and remote != "any":
        actual = normalized(job.get("remote_type"))
        if remote not in {"remote", "hybrid", "onsite"} or actual not in {"remote", "hybrid", "onsite"}:
            record("remote", "review", "Remote preference or job work arrangement is missing or unfamiliar.")
        elif remote == actual:
            record("remote", "keep", f"Job work arrangement matches {remote}.")
        else:
            record("remote", "reject", f"Job is {actual}; applicant requires {remote}.")

    locations = preferences.get("preferred_locations") or []
    if locations:
        actual = normalized(job.get("location"))
        wanted = [normalized(location) for location in locations]
        if _ambiguous_location(actual):
            record("location", "review", "Job location is missing or ambiguous; a remote label does not establish geographic eligibility.")
        elif actual in [location for location in wanted if not _ambiguous_location(location)]:
            record("location", "keep", f"Job location {job.get('location')!r} exactly matches a preferred location after normalization.")
        elif any(_ambiguous_location(location) for location in wanted):
            record("location", "review", "A preferred location is ambiguous; geographic eligibility cannot be resolved.")
        else:
            record("location", "reject", f"Job location {job.get('location')!r} does not exactly match any preferred location; no geography was inferred.")

    roles = preferences.get("target_roles") or []
    if roles:
        title = normalized(job.get("title"))
        phrases = [normalized(role) for role in roles]
        if not title:
            record("role", "review", "Job title is missing.")
        elif any(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", title) for phrase in phrases):
            record("role", "keep", "Job title contains a configured target role as a whole phrase.")
        elif not all(phrases):
            record("role", "review", "A target role is blank and cannot be matched.")
        else:
            record("role", "reject", f"Job title {job.get('title')!r} contains no configured target-role phrase.")

    threshold = preferences.get("minimum_salary")
    if threshold is not None:
        low, high = job.get("salary_min"), job.get("salary_max")
        currency = normalized(preferences.get("salary_currency"))
        job_currency = normalized(job.get("salary_currency"))
        period = normalized(preferences.get("salary_period"))
        job_period = normalized(job.get("salary_period"))
        if not all(_amount(value) for value in (threshold, low, high)) or low > high:
            record("salary", "review", "Compensation is missing, non-finite, negative, or has an inconsistent range.")
        elif not re.fullmatch(r"[a-z]{3}", currency) or currency != job_currency:
            record("salary", "review", "Salary currencies are missing, unfamiliar, or incompatible; no currency conversion is performed.")
        elif period not in PAY_PERIODS or period != job_period:
            record("salary", "review", "Salary pay periods are missing, unfamiliar, or incompatible; no hourly/annual conversion is performed.")
        elif high < threshold:
            record("salary", "reject", f"Job maximum {high:g} {currency.upper()} {period} is below required minimum {threshold:g}.")
        elif low >= threshold:
            record("salary", "keep", f"Job minimum {low:g} {currency.upper()} {period} meets required minimum {threshold:g}.")
        else:
            record("salary", "review", f"Job range {low:g}–{high:g} {currency.upper()} {period} overlaps required minimum {threshold:g}.")

    if not reasons:
        record("preferences", "keep", "No restrictive preferences are configured.")
    outcomes = {reason["outcome"] for reason in reasons}
    decision = "reject" if "reject" in outcomes else "review" if "review" in outcomes else "keep"
    return Result(decision, reasons)
