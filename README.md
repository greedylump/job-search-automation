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
```

## Local setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1  # or source .venv/bin/activate on Unix-like systems
pip install -e .
```

## First-run commands

Create the SQLite database and tables:

```bash
python -m jobsearch.scripts.init_db
```

Run the sample JSON fixture ingestion pipeline:

```bash
python -m jobsearch.scripts.run_fixture_ingestion
```

Run tests:

```bash
pytest
```

## Configuration

This project reads configuration from environment variables with the `JOBSEARCH_` prefix. Example:

```bash
export JOBSEARCH_DATABASE_URL=sqlite:///./jobsearch.db
export JOBSEARCH_LOG_LEVEL=INFO
```

The default SQLite location is `sqlite:///./jobsearch.db`.
