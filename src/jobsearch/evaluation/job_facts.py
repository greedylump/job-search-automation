"""Applicant-independent facts from stored fields, with exact source evidence.

No networking or clock reads. Extraction is deliberately narrow: an absent fact
is unknown, not false. The source record and its original labels are not mutated.
"""
from datetime import datetime, timedelta, timezone
import re

from jobsearch.evaluation.rules import normalized

FACTS_VERSION = "job-facts-v1"
EMPLOYMENT_ALIASES = {
    "full_time": "full_time", "full time": "full_time", "full-time": "full_time",
    "part_time": "part_time", "part time": "part_time", "part-time": "part_time",
    "w2_contract": "w2_contract", "w-2 contract": "w2_contract", "w2 contract": "w2_contract",
    "c2c": "c2c", "corp-to-corp": "c2c", "corp to corp": "c2c",
    "contract": "contract", "consulting": "consulting", "temporary": "temporary",
}


def parse_as_of(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("as-of must include a UTC offset")
    return result.astimezone(timezone.utc)


def evidence(field: str, text: str, start: int, end: int) -> dict:
    return dict(field=field, start=start, end=end, text=text[start:end])


def _closing(job: dict, as_of: datetime | None) -> dict:
    description = job.get("description") or ""
    # Only the labeled field emitted by our USAJOBS normalizer is supported.
    if job.get("ats_type") != "usajobs":
        return dict(status="unknown", deadline=None, evidence=[], reason="No supported source deadline field.")
    matches = list(re.finditer(r"(?m)^Application closes:[ \t]*([^\r\n]*)$", description))
    proof = [evidence("description", description, m.start(), m.end()) for m in matches]
    if len(matches) != 1:
        return dict(status="unknown", deadline=None, evidence=proof,
                    reason="Missing or multiple closing-date fields.")
    raw = matches[0][1].strip()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?", raw):
            raise ValueError("Not an ISO source deadline")
        deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if deadline.tzinfo is not None:
            earliest = latest = deadline.astimezone(timezone.utc)
            precision = "offset_datetime"
        else:
            # Do not invent a source timezone. Use a full-day guard in either
            # direction; date-only deadlines include the entire reported day.
            earliest = deadline.replace(tzinfo=timezone.utc) - timedelta(days=1)
            end = deadline + timedelta(days=1) if len(raw) == 10 else deadline
            latest = end.replace(tzinfo=timezone.utc) + timedelta(days=1)
            precision = "date_only" if len(raw) == 10 else "timezone_unknown"
    except (ValueError, OverflowError):
        return dict(status="unknown", deadline=raw, evidence=proof, reason="Unrecognized or invalid closing date.")
    status = ("unknown" if as_of is None else "past_reported_deadline" if as_of >= latest
              else "before_reported_deadline" if as_of < earliest else "deadline_uncertain")
    return dict(status=status, deadline=raw, precision=precision,
                earliest_utc=earliest.isoformat(), latest_utc=latest.isoformat(), evidence=proof,
                reason="Reported deadline only; earlier closure or extensions are not verified. Unknown timezones use a 24-hour guard.")


def _requirements(job: dict) -> list[dict]:
    description = job.get("description") or ""
    if job.get("ats_type") != "usajobs":
        return []
    # Isolate our source-labeled requirements section; unrelated-role lists,
    # summaries, and qualifications must not become binding requirements.
    sections = list(re.finditer(r"(?m)^Requirements:[ \t]*", description))
    if len(sections) != 1:
        return []
    start = sections[0].end()
    stop = description.find("\n\n", start)
    stop = len(description) if stop == -1 else stop
    body = description[start:stop]
    level = r"(?P<level>Secret|Top Secret)"
    patterns = [
        ("required", rf"This position requires (?:a |an )?{level}(?: security)? clearance[.!]?"),
        ("required", rf"(?:You must|Must) (?:be able to )?obtain and maintain (?:a |an )?{level}(?: security)? clearance[.!]?"),
        ("active_required", rf"(?:You must|Must) (?:currently )?(?:hold|possess) (?:an? )?active {level}(?: security)? clearance[.!]?"),
    ]
    found = []
    for sentence in re.finditer(r"[^.!?\n]+[.!?]?", body):
        text = sentence[0].strip()
        for requirement, pattern in patterns:
            match = re.fullmatch(pattern, text, re.I)
            if match:
                begin = start + sentence.start() + len(sentence[0]) - len(sentence[0].lstrip())
                found.append(dict(kind="security_clearance", requirement=requirement,
                                  value=normalized(match["level"]),
                                  evidence=evidence("description", description, begin, begin + len(text))))
                break
    # Contradictory/conditional clearance language in this same section makes
    # even an affirmative match uncertain. False negatives are preferable here.
    clearance_sentences = [m[0] for m in re.finditer(r"[^.!?\n]+[.!?]?", body)
                           if re.search(r"\bclearance\b", m[0], re.I)]
    if any(re.search(r"\b(no|not|may|might|if|waiv\w*|except\w*|optional|preferred)\b", s, re.I)
           for s in clearance_sentences):
        return []
    # Follow-up sentences may refer to "this requirement" rather than repeat
    # "clearance". Do not promote examples or potentially waived requirements.
    if re.search(r"\b(waiv\w*|except\w*|example|hypothetical)\b|\bnot required\b", body, re.I):
        return []
    return found


def extract(job: dict, as_of: datetime | None = None) -> dict:
    if as_of is not None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
    raw = job.get("employment_type")
    return dict(version=FACTS_VERSION,
                employment=dict(value=EMPLOYMENT_ALIASES.get(normalized(raw)),
                                evidence=[evidence("employment_type", raw, 0, len(raw))] if isinstance(raw, str) else []),
                availability=_closing(job, as_of), requirements=_requirements(job))
