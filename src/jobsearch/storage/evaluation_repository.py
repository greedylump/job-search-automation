from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsearch.evaluation import rules
from jobsearch.models import Job, JobEvaluation
from jobsearch.storage.applicant_repository import ApplicantRepository


PREFERENCE_FIELDS = (
    "remote_preference", "preferred_locations", "target_roles", "minimum_salary",
    "salary_currency", "salary_period",
)
JOB_FIELDS = (
    "title", "company", "location", "remote_type", "salary_min", "salary_max",
    "salary_currency", "salary_period",
)


def _snapshot(record, fields: tuple[str, ...]) -> dict:
    values = {field: getattr(record, field) for field in fields}
    # Retain malformed non-finite legacy values as explicit strings in valid JSON.
    for field, value in values.items():
        if isinstance(value, float) and not math.isfinite(value):
            values[field] = str(value)
    return json.loads(json.dumps(values, allow_nan=False))


class EvaluationRepository:
    """One immutable evaluation per job/applicant/distinct input and rule version."""

    def __init__(self, session: Session):
        self.session = session

    def _applicant(self, applicant_id: int):
        applicant = ApplicantRepository(self.session).get_by_id(applicant_id)
        if applicant is None:
            raise ValueError(f"Applicant {applicant_id} does not exist")
        return applicant

    def evaluate_jobs(self, applicant_id: int, job_id: int | None = None) -> tuple[list[JobEvaluation], dict[str, int]]:
        applicant = self._applicant(applicant_id)
        statement = select(Job).order_by(Job.id)
        if job_id is not None:
            if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
                raise ValueError("job_id must be a positive integer")
            statement = statement.where(Job.id == job_id)
        jobs = self.session.scalars(statement).all()
        if job_id is not None and not jobs:
            raise ValueError(f"Job {job_id} does not exist")
        summary = {"keep": 0, "reject": 0, "review": 0, "unchanged": 0}
        evaluations = []
        for job in jobs:
            context = {
                "applicant_id": applicant.id, "job_id": job.id,
                "preferences": _snapshot(applicant, PREFERENCE_FIELDS),
                "job": _snapshot(job, JOB_FIELDS),
                "rules_version": rules.RULES_VERSION,
            }
            fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()
            existing = self.session.scalar(select(JobEvaluation).where(
                JobEvaluation.job_id == job.id,
                JobEvaluation.applicant_id == applicant.id,
                JobEvaluation.input_fingerprint == fingerprint,
            ))
            if existing is not None:
                evaluations.append(existing)
                summary["unchanged"] += 1
                continue
            result = rules.evaluate(context["preferences"], context["job"])
            evaluation = JobEvaluation(
                job_id=job.id, applicant_id=applicant.id,
                decision=result.decision, reasons=result.reasons,
                evaluated_at=datetime.now(timezone.utc), rules_version=rules.RULES_VERSION,
                input_fingerprint=fingerprint, input_context=context,
            )
            self.session.add(evaluation)
            self.session.flush()
            evaluations.append(evaluation)
            summary[result.decision] += 1
        return evaluations, summary

    def list_results(self, applicant_id: int, decision: str | None = None) -> list[JobEvaluation]:
        self._applicant(applicant_id)
        if decision is not None and decision not in {"keep", "reject", "review"}:
            raise ValueError("decision must be keep, reject, or review")
        statement = select(JobEvaluation).where(JobEvaluation.applicant_id == applicant_id)
        if decision is not None:
            statement = statement.where(JobEvaluation.decision == decision)
        return list(self.session.scalars(statement.order_by(JobEvaluation.id.desc())))
