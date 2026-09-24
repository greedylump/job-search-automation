"""Read-only SQLite inspection: no migrations, applicant reads, or HTTP."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from jobsearch.evaluation.job_facts import extract, parse_as_of


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Existing SQLite file")
    parser.add_argument("--as-of", type=parse_as_of, default=None, help="ISO datetime with offset; defaults to current UTC")
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)
    if args.job_id is not None and args.job_id <= 0:
        parser.error("job-id must be positive")
    as_of = args.as_of or datetime.now(timezone.utc)
    with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        query = "SELECT id, title, source, employment_type, ats_type, description FROM jobs"
        rows = connection.execute(query + (" WHERE id=?" if args.job_id else "") + " ORDER BY id",
                                  (args.job_id,) if args.job_id else ())
        records = [dict(job_id=r["id"], title=r["title"], source=r["source"], facts=extract(dict(r), as_of)) for r in rows]
    if args.job_id is not None and not records:
        parser.error("Job does not exist")
    output = dict(as_of=as_of.isoformat(), jobs=len(records),
                  availability=dict(Counter(r["facts"]["availability"]["status"] for r in records)),
                  employment=dict(Counter(r["facts"]["employment"]["value"] or "unknown" for r in records)),
                  jobs_with_clearance_evidence=sum(bool(r["facts"]["requirements"]) for r in records))
    if not args.summary_only:
        output["records"] = records
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
