import argparse
import json
import os
from jobsearch.config.settings import get_settings
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.history_retention import retain_history


def main(argv=None):
    settings = get_settings()
    parser = argparse.ArgumentParser(description='Roll up expired request/run history; dry run by default')
    parser.add_argument('--database-url', default=settings.database_url)
    parser.add_argument('--request-days', type=int, default=int(os.getenv('JOBSEARCH_REQUEST_RETENTION_DAYS', '180')))
    parser.add_argument('--run-days', type=int, default=int(os.getenv('JOBSEARCH_RUN_RETENTION_DAYS', '365')))
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    run_migrations(args.database_url)
    print(json.dumps(retain_history(args.database_url, request_days=args.request_days,
        run_days=args.run_days, limit=args.limit, apply=args.apply), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
