"""Inspect, pause, or explicitly resume collection without contacting providers."""
import argparse
import json

from jobsearch.config.settings import get_settings
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.collection_control import control


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url')
    parser.add_argument('action', choices=['status', 'pause', 'resume'])
    args = parser.parse_args(argv)
    url = args.database_url or get_settings().database_url
    run_migrations(url)
    report = control(url, args.action)
    print(json.dumps(report, indent=2))
    return 2 if report['paused'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
