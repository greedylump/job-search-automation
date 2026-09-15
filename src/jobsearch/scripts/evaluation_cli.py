from __future__ import annotations

import argparse
from sqlalchemy.orm import object_session
from jobsearch.models import JobSource

from jobsearch.config.settings import get_settings
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.database import close_session, get_session
from jobsearch.storage.evaluation_repository import EvaluationRepository


def _positive_id(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ID must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("ID must be a positive integer")
    return number


def _print_result(evaluation) -> None:
    snapshot = (evaluation.input_context or {}).get("job")
    if snapshot is None:
        snapshot = {"title": evaluation.job.title, "company": evaluation.job.company}
    print(f"evaluation={evaluation.id} job={evaluation.job_id} | {snapshot.get('title') or '(untitled)'} | "
          f"{snapshot.get('company') or '(unknown company)'} | {evaluation.decision or 'legacy'}")
    print(f"  evaluated={evaluation.evaluated_at} rules={evaluation.rules_version or 'legacy/unknown'}")
    session = object_session(evaluation)
    config = session.get(JobSource, evaluation.job.source) if session is not None else None
    if evaluation.job.source == "remotive" or (config is not None and config.adapter_type == "remotive"):
        print(f"  Source: Remotive | {evaluation.job.job_url or 'No source link supplied'}")
    for reason in evaluation.reasons or []:
        print(f"  {reason['check']} [{reason['outcome']}]: {reason['message']}")
    if not evaluation.reasons:
        print(f"  {evaluation.rejection_reason or 'Legacy evaluation: no deterministic reasons recorded.'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate stored jobs using applicant preferences; no AI calls.")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="evaluate stored jobs and preserve distinct input history")
    evaluate.add_argument("--applicant-id", required=True, type=_positive_id)
    evaluate.add_argument("--job-id", type=_positive_id)
    listing = commands.add_parser("list", help="list evaluation history, newest first")
    listing.add_argument("--applicant-id", required=True, type=_positive_id)
    listing.add_argument("--decision", choices=("keep", "reject", "review"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session = None
    try:
        url = get_settings().database_url
        run_migrations(url)
        session = get_session(url)
        repository = EvaluationRepository(session)
        if args.command == "evaluate":
            evaluations, summary = repository.evaluate_jobs(args.applicant_id, args.job_id)
            session.commit()
            for evaluation in evaluations:
                _print_result(evaluation)
            print(f"Summary: kept={summary['keep']} rejected={summary['reject']} "
                  f"review-needed={summary['review']} unchanged/skipped={summary['unchanged']}")
        else:
            evaluations = repository.list_results(args.applicant_id, args.decision)
            for evaluation in evaluations:
                _print_result(evaluation)
            print(f"Results: {len(evaluations)} (historical evaluations)")
        return 0
    except Exception as exc:
        if session is not None:
            session.rollback()
        raise SystemExit(f"error: {exc}") from exc
    finally:
        close_session(session)


if __name__ == "__main__":
    raise SystemExit(main())
