import argparse
import json
import os

from jobsearch.storage.maintenance import snapshots


def main(argv=None):
    parser = argparse.ArgumentParser(description='Expire disposable JSON response snapshots; dry run by default')
    parser.add_argument('--snapshot-dir', required=True, help='Dedicated directory containing only disposable response snapshots')
    parser.add_argument('--days', type=int, default=int(os.getenv('JOBSEARCH_SNAPSHOT_RETENTION_DAYS', '7')))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error('--days must be positive')
    files = snapshots(args.snapshot_dir, days=args.days, apply=args.apply)
    print(json.dumps(dict(applied=args.apply, files=files, bytes=sum(f['bytes'] for f in files)), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
