# Job Search Automation

A small Python project for ingesting jobs from one source, normalizing them into a common model, storing them in SQLite, deduplicating them, applying deterministic filtering rules, and recording processing metrics.

## Project goal for v1

The first milestone intentionally only actively uses the `Job` and `ProcessingRun` models. The `JobEvaluation` and `Application` models are included in the schema for future growth, but AI scoring, Gmail integration, browser automation, and the dashboard are intentionally out of scope.

## Project structure

```text
src/jobsearch/
    collectors/
    config/
    filtering/
    models/
    normalization/
    scripts/
    storage/

tests/
    test_end_to_end_ingestion.py
    test_models.py
```

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1  # or source .venv/bin/activate on Unix-like systems
pip install -e ".[dev]"
```

## First-run commands

Create or migrate the SQLite database from the Alembic chain:

```powershell
python -m jobsearch.scripts.init_db
```

To target a different database instance in the same shell, export:

```powershell
$env:JOBSEARCH_DATABASE_URL = "sqlite:///./jobsearch.db"
```

Run the sample JSON fixture ingestion pipeline:

```powershell
python -m jobsearch.scripts.run_fixture_ingestion
```

Expected result: the fixture runner writes one `ProcessingRun` row and records metrics such as `jobs_seen`, `jobs_new`, `jobs_deduplicated`, and `jobs_filtered` for the run.

Run tests:

```powershell
python -m pytest -q
```

## Configuration

This project reads configuration from environment variables with the `JOBSEARCH_` prefix. Example:

```powershell
$env:JOBSEARCH_DATABASE_URL = "sqlite:///./jobsearch.db"
$env:JOBSEARCH_LOG_LEVEL = "INFO"
```

The default SQLite location is `sqlite:///./jobsearch.db`.

## Migrations

The canonical schema manager is Alembic. Direct table creation with `Base.metadata.create_all()` is intentionally not supported. Upgrade the local database in the repository root with:

```powershell
python -m jobsearch.scripts.init_db
```

The migration chain in `alembic/versions/` should produce a head revision of `20260913_05` and the `jobs` table must expose the unique `source + source_job_id` index shape recorded in the model.


## Applicant profiles

Keep real applicant JSON files in `data/private/` (Git-ignored). Create that
folder locally with `New-Item -ItemType Directory -Force data/private`.
`data/applicant_sample.json` is a tracked fictional example; never put real
personal information into that sample. Backups belong in ignored `data/backups/`.
Git ignore rules prevent accidental tracking, but do not encrypt these files.

```powershell
python -m jobsearch.scripts.applicant_cli create --input data/private/applicant.json
# Use the ID printed by create; IDs are not assumed to start at 1.
$applicantId = 42 # replace with the actual printed ID
python -m jobsearch.scripts.applicant_cli view --id $applicantId
python -m jobsearch.scripts.applicant_cli update --id $applicantId --input data/private/update.json
python -m alembic current
python -m alembic upgrade head
```

Creation requires a nonblank `full_name`. Updates are partial: omitted fields
remain unchanged, including `full_name`. For example, an update file can contain
only `{"skills": ["Python", "SQL"]}`. IDs and timestamps cannot be supplied.
Unknown fields and invalid types are rejected. Optional text fields accept strings
or null. `skills`, `target_roles`, and `preferred_locations` require lists of
strings; use `[]` to clear a list (null is rejected). `minimum_salary` accepts
null or a finite nonnegative number, excluding booleans. Remote preference accepts
`remote`, `hybrid`, `onsite`, `any`, or null; surrounding whitespace and case are
normalized. Invalid input and missing IDs produce nonzero exit codes.

Both direct Alembic commands and application commands read `.env`; shell variables
win over `.env`. An explicit Python `run_migrations(database_url=...)` argument wins
over both. The final migration head is `20260913_05`: `_03` retains its historical
`completed` default, `_04` adds applicants and nullable links, and `_05` changes
only the default for new processing runs to `running`, preserving existing statuses.

## Fixture counts

Each invocation records one processing run. Counts below assume a fresh database
for the initial run, followed by the same fixture again.

| Fixture | Seen per run | Initial new / deduplicated / filtered | Repeated new / deduplicated / filtered |
| --- | ---: | --- | --- |
| `jobs_fixture.json` | 2 | 2 / 0 / 0 | 0 / 2 / 0 |
| `jobs_fixture_with_duplicates.json` | 3 | 2 / 1 / 0 | 0 / 3 / 0 |
| `jobs_fixture_with_filtered.json` | 3 | 1 / 0 / 2 | 0 / 1 / 2 |
| `jobs_fixture_missing_source_id.json` | 2 | 0 / 0 / 2 | 0 / 0 / 2 |

The obsolete ignored `data/test-jobsearch.db` is not used by these commands.
