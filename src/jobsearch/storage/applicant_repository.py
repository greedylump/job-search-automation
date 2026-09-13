from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsearch.models.applicant import Applicant


class ApplicantRepository:
    """Repository for applicant records and profile updates."""

    ALLOWED_REMOTE_PREFERENCES = {"remote", "hybrid", "onsite", "any"}

    def __init__(self, session: Session):
        self.session = session

    TEXT_FIELDS = {
        "email", "phone", "location", "professional_summary", "experience_summary",
        "linkedin_url", "github_url", "portfolio_url", "salary_currency",
        "remote_preference",
    }
    LIST_FIELDS = {"skills", "target_roles", "preferred_locations"}

    def validate_payload(self, payload: dict[str, Any], *, partial: bool = False) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Applicant payload must be a JSON object")
        unknown = payload.keys() - (self.TEXT_FIELDS | self.LIST_FIELDS | {"full_name", "minimum_salary"})
        if unknown:
            raise ValueError(f"Unknown or protected fields: {', '.join(sorted(unknown))}")
        if not partial or "full_name" in payload:
            name = payload.get("full_name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("full_name is required and must be a non-empty string")
        for key in self.TEXT_FIELDS:
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be a string or null")
        email = payload.get("email")
        if email is not None and "@" not in email:
            raise ValueError("email must contain '@'")
        remote = payload.get("remote_preference")
        if remote is not None and remote.strip().lower() not in self.ALLOWED_REMOTE_PREFERENCES:
            raise ValueError("remote_preference must be one of: remote, hybrid, onsite, any, or null")
        for key in self.LIST_FIELDS:
            if key in payload:
                value = payload[key]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError(f"{key} must be a JSON list of strings; use [] to clear it")
        salary = payload.get("minimum_salary")
        if salary is not None:
            try:
                valid = not isinstance(salary, bool) and isinstance(salary, (int, float)) and math.isfinite(salary) and salary >= 0
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("minimum_salary must be finite, nonnegative, and numeric (not boolean)")

    def _normalized(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        if "full_name" in result:
            result["full_name"] = result["full_name"].strip()
        if result.get("remote_preference") is not None:
            result["remote_preference"] = result["remote_preference"].strip().lower()
        for key in self.LIST_FIELDS & result.keys():
            result[key] = list(result[key])
        return result

    def create_from_payload(self, payload: dict[str, Any]) -> Applicant:
        self.validate_payload(payload)
        applicant = Applicant(**self._normalized(payload))
        self.session.add(applicant)
        self.session.flush()
        return applicant

    def from_json_file(self, file_path: str | Path) -> Applicant:
        with Path(file_path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Applicant JSON input must be an object")
        return self.create_from_payload(payload)

    def get_by_id(self, applicant_id: int) -> Applicant | None:
        if (isinstance(applicant_id, bool) or not isinstance(applicant_id, int)) or applicant_id <= 0:
            raise ValueError("applicant_id must be a positive integer")
        return self.session.get(Applicant, applicant_id)

    def list(self) -> list[Applicant]:
        statement = select(Applicant).order_by(Applicant.id.asc())
        return list(self.session.execute(statement).scalars().all())

    def update_from_payload(self, applicant_id: int, payload: dict[str, Any]) -> Applicant:
        self.validate_payload(payload, partial=True)
        applicant = self.get_by_id(applicant_id)
        if applicant is None:
            raise ValueError(f"Applicant {applicant_id} does not exist")
        for key, value in self._normalized(payload).items():
            setattr(applicant, key, value)
        self.session.flush()
        return applicant
