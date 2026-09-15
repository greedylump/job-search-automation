import argparse
import json
from pathlib import Path

from jobsearch.config.settings import get_settings
from jobsearch.ingestion.runner import run_collector, run_enabled
from jobsearch.scripts.init_db import run_migrations
from jobsearch.storage.source_repository import SourceRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage mutable collector instances and run their adapters.")
    parser.add_argument("--database-url", help="Database containing collector configuration, state, and jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    create = commands.add_parser("create")
    create.add_argument("--input", type=Path, required=True)
    update = commands.add_parser("update")
    update.add_argument("--name", required=True)
    update.add_argument("--input", type=Path, required=True)
    run = commands.add_parser("run")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--name")
    target.add_argument("--all", action="store_true", help="Run enabled instances once")
    args = parser.parse_args(argv)
    try:
        url = args.database_url or get_settings().database_url
        run_migrations(url)
        repo = SourceRepository(url)
        if args.command in {"create", "update"}:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            config = repo.configure(payload, name=args.name if args.command == "update" else None)
            print(f"Saved collector {config.name} ({config.adapter_type}); enabled={config.enabled}")
        elif args.command == "list":
            for config in repo.list():
                print(json.dumps({column.name: getattr(config, column.name) for column in config.__table__.columns}, default=str))
        else:
            if args.all:
                results, errors = run_enabled(database_url=url)
            else:
                results, errors = [run_collector(args.name, database_url=url)], {}
            for result in results:
                print(f"{result.source}: {result.status} | seen={result.records_seen} new={result.jobs_new} "
                      f"duplicates={result.jobs_deduplicated} invalid={result.records_invalid}")
                if result.skip_reason:
                    print(f"  {result.skip_reason}; next eligible UTC={result.next_eligible_at}")
            for name, error in errors.items():
                print(f"{name}: failed | {error}")
            if errors:
                return 1
        return 0
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
