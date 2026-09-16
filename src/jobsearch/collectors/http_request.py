"""Request descriptions and deliberately minimal persisted metadata."""
from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import parse_qsl, urlsplit, urlunsplit


@dataclass(frozen=True)
class RequestSpec:
    url: str
    purpose: str = "list"
    headers: dict[str, str] = field(default_factory=dict)

    def metadata(self) -> dict:
        parts = urlsplit(self.url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError("HTTP collection requires an HTTPS URL without userinfo or fragment")
        if self.purpose not in {"list", "detail", "taxonomy"}:
            raise ValueError("Unknown request purpose")
        # Arbitrary filters/credentials are never persisted. Page positions are useful
        # for auditing; opaque cursors receive a fingerprint, never their raw value.
        query = {}
        for key, value in parse_qsl(parts.query):
            key = key.lower()
            if key in {"page", "offset", "skip", "limit", "count", "results_per_page", "resultsperpage"} and value.isascii() and value.isdigit() and len(value) <= 10:
                query[key] = int(value)
            elif key in {"cursor", "page_token"}:
                query[key + "_sha256"] = sha256(value.encode()).hexdigest()
        return {"endpoint": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
                "request_method": "GET", "request_purpose": self.purpose,
                "request_metadata": query}
