from __future__ import annotations

import argparse
import json
from pathlib import Path

from jobsearch.config.settings import get_settings
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.applicant_repository import ApplicantRepository
from jobsearch.storage.database import close_session, get_session


def _load_payload(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Applicant input file must contain a JSON object")
    return payload


def create(args: argparse.Namespace) -> int:
    settings = get_settings()
    run_migrations(settings.database_url)
    session = get_session(settings.database_url)
    try:
        repo = ApplicantRepository(session)
        applicant = repo.create_from_payload(_load_payload(args.input))
        session.commit()
        print(f"created applicant id={applicant.id}")
        return 0
    except Exception as exc:
        session.rollback()
        raise SystemExit(f"error: {exc}") from exc
    finally:
        close_session(session)


def view(args: argparse.Namespace) -> int:
    settings = get_settings()
    run_migrations(settings.database_url)
    session = get_session(settings.database_url)
    try:
        repo = ApplicantRepository(session)
        applicant = repo.get_by_id(args.applicant_id)
        if applicant is None:
            raise SystemExit(f"error: applicant {args.applicant_id} does not exist")
        print(json.dumps({
            "id": applicant.id,
            "full_name": applicant.full_name,
            "email": applicant.email,
            "phone": applicant.phone,
            "location": applicant.location,
            "professional_summary": applicant.professional_summary,
            "experience_summary": applicant.experience_summary,
            "skills": applicant.skills,
            "linkedin_url": applicant.linkedin_url,
            "github_url": applicant.github_url,
            "portfolio_url": applicant.portfolio_url,
            "target_roles": applicant.target_roles,
            "preferred_locations": applicant.preferred_locations,
            "remote_preference": applicant.remote_preference,
            "minimum_salary": applicant.minimum_salary,
            "salary_currency": applicant.salary_currency,
            "created_at": applicant.created_at.isoformat(),
            "updated_at": applicant.updated_at.isoformat(),
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        raise SystemExit(f"error: {exc}") from exc
    finally:
        close_session(session)


def update(args: argparse.Namespace) -> int:
    settings = get_settings()
    run_migrations(settings.database_url)
    session = get_session(settings.database_url)
    try:
        repo = ApplicantRepository(session)
        payload = _load_payload(args.input)
        applicant = repo.update_from_payload(args.applicant_id, payload)
        session.commit()
        print(f"updated applicant id={applicant.id}")
        return 0
    except Exception as exc:
        session.rollback()
        raise SystemExit(f"error: {exc}") from exc
    finally:
        close_session(session)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage an applicant profile for job-search automation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="create an applicant from the supplied JSON input file")
    create_parser.add_argument("--input", required=True, type=Path)
    create_parser.set_defaults(func=create)

    view_parser = subparsers.add_parser("view", help="view a stored applicant profile by explicit id")
    view_parser.add_argument("--id", dest="applicant_id", required=True, type=int)
    view_parser.set_defaults(func=view)

    update_parser = subparsers.add_parser("update", help="update a stored applicant profile by explicit id")
    update_parser.add_argument("--id", dest="applicant_id", required=True, type=int)
    update_parser.add_argument("--input", required=True, type=Path)
    update_parser.set_defaults(func=update)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
