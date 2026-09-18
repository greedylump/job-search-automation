"""Read local collection results without HTTP calls or private applicant data."""
import argparse
import json
from sqlalchemy import select, func
from jobsearch.config.settings import get_settings
from jobsearch.models import Job, ProcessingRun, RequestAttempt, JobSource, DailyMetric
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.collection_control import control
from jobsearch.storage.database import get_session, close_session


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', default=get_settings().database_url)
    args = parser.parse_args(argv)
    run_migrations(args.database_url)
    storage = control(args.database_url)
    session = get_session(args.database_url)
    try:
        sources = []
        for source in session.scalars(select(JobSource).order_by(JobSource.name)):
            runs = list(session.scalars(select(ProcessingRun).where(ProcessingRun.source == source.name)
                .order_by(ProcessingRun.id.desc()).limit(10)))
            jobs = session.scalar(select(func.count()).select_from(Job).where(Job.source == source.name))
            sources.append(dict(name=source.name, enabled=source.enabled, jobs=jobs,
                next_due_at=source.next_due_at, last_complete_refresh_at=source.last_complete_refresh_at,
                attempts_retained=session.scalar(select(func.count()).select_from(RequestAttempt).where(RequestAttempt.source == source.name)),
                recent_runs=[{field: getattr(run, field) for field in ('id','started_at','status','records_seen',
                    'jobs_new','jobs_deduplicated','records_invalid','pages_collected','skip_reason')} for run in runs]))
        aggregates = [dict(day=row.day, source=row.source, kind=row.kind, dimensions=row.dimensions,
                           rows=row.rows, totals=row.totals) for row in session.scalars(
                               select(DailyMetric).order_by(DailyMetric.day.desc()).limit(100))]
        print(json.dumps(dict(storage=storage, sources=sources, archived_groups_latest_100=aggregates), default=str, indent=2))
    finally:
        close_session(session)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
