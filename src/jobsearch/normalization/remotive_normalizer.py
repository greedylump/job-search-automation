from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from jobsearch.models.job import Job
from jobsearch.normalization.json_normalizer import JsonJobNormalizer


def _text(value: Any) -> str | None:
    return unescape(value).strip() if isinstance(value, str) and value.strip() else None


class _DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class RemotiveJobNormalizer:
    """Map Remotive fields without inferring salary units or geographic eligibility."""

    @staticmethod
    def normalize(payload: dict[str, Any]) -> Job:
        identifier = payload.get("id")
        if isinstance(identifier, bool) or not isinstance(identifier, (int, str)):
            identifier = None
        elif isinstance(identifier, int) and identifier <= 0:
            identifier = None
        elif isinstance(identifier, str):
            identifier = identifier.strip() or None
        title = _text(payload.get("title"))
        description = _DescriptionParser()
        raw_description = payload.get("description")
        description.feed(raw_description if isinstance(raw_description, str) else "")
        plain_description = " ".join(" ".join(description.parts).split())
        salary = _text(payload.get("salary"))
        if salary:
            plain_description = f"Salary (source text): {salary}\n\n{plain_description}"
        url = _text(payload.get("url"))
        try:
            parsed = urlsplit(url or "")
            if parsed.scheme != "https" or parsed.hostname not in {"remotive.com", "www.remotive.com"} or parsed.username:
                url = None
        except ValueError:
            url = None
        return JsonJobNormalizer.normalize({
            "source_job_id": identifier,
            "title": title,
            "company": _text(payload.get("company_name")),
            "location": _text(payload.get("candidate_required_location")),
            "remote_type": "remote",
            "employment_type": _text(payload.get("job_type")),
            "description": plain_description or None,
            "job_url": url,
            "posted_at": _text(payload.get("publication_date")),
        }, source="remotive")
