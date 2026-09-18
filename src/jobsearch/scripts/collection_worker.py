import argparse
import logging
import signal
import time
from threading import Event

from jobsearch.config.settings import get_settings
from jobsearch.ingestion.worker import run_due
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.maintenance import configure_worker_logging


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run due live collectors serially with persistent budgets")
    parser.add_argument('--database-url')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--loop', action='store_true')
    parser.add_argument('--poll-seconds', type=int, default=60)
    parser.add_argument('--max-collectors', type=int, default=20)
    parser.add_argument('--max-runtime-seconds', type=int, help='Stop the loop after a bounded observation period')
    args = parser.parse_args(argv)
    if args.poll_seconds < 60 or not 1 <= args.max_collectors <= 1000:
        parser.error('poll-seconds must be >=60; max-collectors must be between 1 and 1000')
    if args.max_runtime_seconds is not None and args.max_runtime_seconds < 1:
        parser.error('max-runtime-seconds must be positive')
    url = args.database_url or get_settings().database_url
    run_migrations(url)
    configure_worker_logging()
    stop = Event()
    deadline = time.monotonic() + args.max_runtime_seconds if args.max_runtime_seconds else None
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        while not stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            results, errors = run_due(url, limit=args.max_collectors, stopped=stop.is_set)
            for result in results:
                print(f'{result.source}: {result.status}; new={result.jobs_new}; pages={result.pages_collected}', flush=True)
            for name, error in errors.items():
                logging.error('Collector %s failed: %s', name, error)
            if args.once:
                return 1 if errors else 0
            delay = args.poll_seconds if deadline is None else min(args.poll_seconds, max(0, deadline - time.monotonic()))
            stop.wait(delay)
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
