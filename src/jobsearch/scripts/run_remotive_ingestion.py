from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from jobsearch.collectors.remotive_collector import RemotiveCollector
from jobsearch.config.settings import get_settings
from jobsearch.ingestion.runner import run_collector
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.source_repository import SourceRepository
from jobsearch.models import Job, ProcessingRun
from jobsearch.storage.database import close_session, get_session


def run_remotive_ingestion(*, database_url: str | None = None,
                           replay_path: str | Path | None = None,
                           snapshot_path: str | Path | None = None) -> ProcessingRun:
    if replay_path is not None and snapshot_path is not None:
        raise ValueError("Replay and snapshot cannot be combined")
    database_url = database_url or get_settings().database_url
    run_migrations(database_url)
    repo = SourceRepository(database_url)
    if not any(config.name == "remotive" for config in repo.list()):
        repo.configure({"name": "remotive", "adapter_type": "remotive"})
    collector = RemotiveCollector(database_url, snapshot_path)
    collect = (collector.collect if snapshot_path is not None else None) if replay_path is None else lambda: collector.replay(replay_path)
    return run_collector("remotive", collect_override=collect, database_url=database_url,
                         collection_mode="live" if replay_path is None else "replay")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Remotive when its persistent request interval permits.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, help="Explicitly process a saved response without HTTP or freshness updates")
    mode.add_argument("--snapshot", type=Path, help="Save this eligible live response for debugging/recovery; path must not exist")
    parser.add_argument("--database-url", help="Override JOBSEARCH_DATABASE_URL for this run")
    parser.add_argument("--show", type=int, default=10, help="Number of stored jobs to display (0-100)")
    parser.add_argument("--title", default="", help="Case-insensitive title substring for display only; all feed jobs are ingested")
    args = parser.parse_args(argv)
    if not 0 <= args.show <= 100:
        parser.error("--show must be between 0 and 100")
    session = None
    try:
        run = run_remotive_ingestion(database_url=args.database_url, replay_path=args.replay, snapshot_path=args.snapshot)
        print(f"Source: Remotive | run={run.id} status={run.status}")
        print(f"Collection mode: {run.collection_mode}")
        if run.skip_reason:
            print(f"Skip reason: {run.skip_reason}; next eligible UTC: {run.next_eligible_at}")
        print(f"Records seen={run.records_seen} new={run.jobs_new} "
              f"deduplicated={run.jobs_deduplicated} invalid={run.records_invalid}")
        reasons = run.invalid_reason_counts or {}
        print(f"Invalid reasons: non-object={reasons.get('non_object', 0)} "
              f"missing-ID={reasons.get('missing_source_id', 0)} invalid-title={reasons.get('invalid_title', 0)}")
        if args.show:
            session = get_session(args.database_url)
            statement = select(Job).where(Job.source == "remotive").order_by(Job.posted_at.desc(), Job.id.desc())
            if args.title:
                statement = statement.where(Job.title.icontains(args.title, autoescape=True))
            jobs = session.scalars(statement.limit(args.show)).all()
            print("Stored results from Remotive (not applicant fit scores; older stored listings may have closed):")
            for job in jobs:
                print(f"job={job.id} | {job.title} | {job.company} | {job.location or 'Location unspecified'}")
                print(f"  Source: Remotive | {job.job_url or 'No source link supplied'}")
            if not jobs:
                print("No stored titles match this display filter.")
        return 0
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")
    finally:
        close_session(session)


if __name__ == "__main__":
    raise SystemExit(main())
