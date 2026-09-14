# Job Search Automation

A small Python project for ingesting jobs from one source, normalizing them into a common model, storing them in SQLite, deduplicating them, and evaluating stored jobs against applicant preferences with explainable deterministic rules.

## Project goal for v1

Jobs are shared source records. Ingestion rejects invalid source records and records `ProcessingRun` metrics. Applicant-specific decisions are stored separately in `JobEvaluation`; `Application` remains available for future tracking. AI scoring, employer contact, application submission, browser automation, and dashboards are outside this milestone.

## Project structure

```text
src/jobsearch/
    collectors/
    config/
    filtering/
    evaluation/
    models/
    normalization/
    scripts/
    storage/

tests/
    test_end_to_end_ingestion.py
    test_models.py
    test_storage_and_filtering.py
    test_applicants_and_migrations.py
    test_evaluation_rules.py
    test_evaluation_workflow.py
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

To target a different database instance in the same shell, set:

```powershell
$env:JOBSEARCH_DATABASE_URL = "sqlite:///./jobsearch.db"
```

Run the sample JSON fixture ingestion pipeline:

```powershell
python -m jobsearch.scripts.run_fixture_ingestion
```

Expected result: the fixture runner writes one `ProcessingRun` row and records metrics such as `records_seen`, `jobs_new`, `jobs_deduplicated`, and `records_invalid` for the run.

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

The migration chain in `alembic/versions/` should produce a head revision of `20260914_08` and the `jobs` table must expose the unique `source + source_job_id` index shape recorded in the model.


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
over both. The final migration head is `20260914_08`: `_03` retains its historical
`completed` default, `_04` adds applicants and nullable links, and `_05` changes
only the default for new processing runs to `running`, preserving existing statuses.
`_06` adds nullable salary periods and versioned deterministic evaluation history.
Existing salary periods remain unknown; existing evaluations and nullable legacy
applicant links are preserved.
`_07` renames `jobs_seen` to `records_seen` and `jobs_filtered` to
`records_invalid`, preserving historical values without recalculating them.
`_08` adds nullable `invalid_reason_counts`; historical breakdowns remain unknown.

## Fixture counts

Each invocation records one processing run. Counts below assume a fresh database
for the initial run, followed by the same fixture again.

| Fixture | Records seen per run | Initial new / deduplicated / invalid | Repeated new / deduplicated / invalid |
| --- | ---: | --- | --- |
| `jobs_fixture.json` | 2 | 2 / 0 / 0 | 0 / 2 / 0 |
| `jobs_fixture_with_duplicates.json` | 3 | 2 / 1 / 0 | 0 / 3 / 0 |
| `jobs_fixture_with_filtered.json` | 3 | 2 / 0 / 1 | 0 / 2 / 1 |
| `jobs_fixture_missing_source_id.json` | 2 | 0 / 0 / 2 | 0 / 0 / 2 |

The obsolete ignored `data/test-jobsearch.db` is not used by these commands.


The filtered fixture intentionally changed from 1 new / 2 filtered to 2 new / 1
filtered: its onsite job is now stored. `records_invalid` counts invalid source
records (non-object entries, missing source keys, non-string titles, or titles
shorter than two characters after trimming surrounding whitespace),
not applicant rejections. Deduplication and last-seen updates still apply.
Existing stored jobs can be evaluated immediately; no collection is required.
Ingestion does not update other fields of an existing source key.

`records_seen` counts every entry visited in the fixture array (or its `jobs` array),
including non-object entries. Non-object entries are counted as filtered before
normalization; records with source keys are deduplicated before title filtering.
For completed runs, `records_seen = jobs_new + jobs_deduplicated + records_invalid`.
Invalid JSON or an unsupported outer structure fails the run instead of counting
as an individual filtered record.

New fixture runs store `invalid_reason_counts` with three aggregate counters:
`non_object`, `missing_source_id`, and `invalid_title`. Their sum equals
`records_invalid`. Each rejected entry receives one reason, following the existing
validation order; duplicates are still counted before title validation. Failed
runs preserve the reasons counted before failure, even when job inserts roll back.
Historical runs have a null breakdown, not fabricated zero counts. No raw input or
applicant details are stored in this breakdown.

The ingestion log includes a summary such as:
```text
Invalid records: non-object=2; missing ID=1; invalid title=2
```

## Fixture-ingestion checkpoint — 2026-09-14

Fixture ingestion now accounts for malformed entries, rejects non-string titles
without aborting the batch, and persists aggregate rejection reasons on successful
and failed runs. The applicant timestamp test uses a controlled clock so updates
do not depend on operating-system clock resolution.

Verification at this checkpoint:

- Full test suite: **149 passed**.
- A separate temporary database migrated to `20260914_08`; Alembic's schema check
  found no differences from the models.
- A six-entry mixed fixture produced 2 new jobs, 1 duplicate, and 3 invalid records.
  Repeating it produced 0 new jobs, 3 duplicates, and 3 invalid records.
- Both runs saved one rejection for each reason, completed timestamps, zero jobs
  scored, and zero AI cost. Two jobs remained stored.
- Database integrity and foreign-key checks passed. Temporary verification files
  were removed; the project database was not migrated by this verification.

The fixture-ingestion phase is ready for review. The next implementation milestone
is one real job source with conservative collection and reliable error handling.
AI scoring, application automation, and deployment remain later work.

## Profile-to-evaluation workflow (PowerShell)

```powershell
.venv\Scripts\Activate.ps1
$env:JOBSEARCH_DATABASE_URL = "sqlite:///./jobsearch.db"
python -m jobsearch.scripts.init_db
New-Item -ItemType Directory -Force data/private
Copy-Item data/applicant_sample.json data/private/applicant.json
notepad data/private/applicant.json
# Replace the fictional details with your own before creating the profile.
python -m jobsearch.scripts.applicant_cli create --input data/private/applicant.json
$applicantId = [int](Read-Host "Enter the applicant ID printed by create")
python -m jobsearch.scripts.applicant_cli view --id $applicantId
python -m jobsearch.scripts.run_fixture_ingestion
python -m jobsearch.scripts.evaluation_cli evaluate --applicant-id $applicantId
python -m jobsearch.scripts.evaluation_cli list --applicant-id $applicantId
python -m jobsearch.scripts.evaluation_cli list --applicant-id $applicantId --decision keep
# Optional: evaluate just one job using its ID from the result output.
$jobId = [int](Read-Host "Enter an existing job ID")
python -m jobsearch.scripts.evaluation_cli evaluate --applicant-id $applicantId --job-id $jobId
```

Profile updates still use `applicant_cli update --id $applicantId --input
 data/private/update.json` and leave omitted fields unchanged. Run evaluation again
after updating preferences. No real profile is bundled or assumed, and the CLI
requires an explicit applicant ID. Missing/invalid applicant or job IDs and invalid
arguments exit nonzero. An applicant is validated before querying jobs to evaluate.

## Deterministic rules: `preferences-v1`

Every configured check produces a readable reason. The overall result is `reject`
if any check definitely fails, otherwise `review` if any check is unresolved,
otherwise `keep`. All checks run even if an earlier check rejects. Unset preferences
impose no restriction. There are no AI calls, scores, inferred synonyms, or currency
conversions. A keep decision only means these configured checks passed.

| Check | Behavior |
| --- | --- |
| Remote | Null or `any` is unrestricted. `remote`, `hybrid`, or `onsite` must match the job value after case/whitespace normalization. Missing or unfamiliar job values require review. |
| Location | Each preferred location is an exact match after case folding and collapsing whitespace. `Seattle, WA` does not match `Seattle` or `Washington`; no geography is inferred. A concrete unmatched location rejects. Missing/ambiguous job locations require review. |
| Target roles | A normalized target role must appear as a whole phrase in the normalized title, bounded by non-word characters or the string edges. `Data Engineer` matches `Senior Data Engineer II`, but not `Data Engineering`; `Engineer` does not match `Bioengineer`. Punctuation is literal within the phrase. Missing titles or unresolved blank preferences require review. |
| Salary | Both job bounds must be finite, nonnegative, and ordered. Currency identifiers must match (three letters, case-insensitive), and pay periods must match. Maximum below the threshold rejects; minimum at or above it passes; a range spanning the threshold requires review. Missing or incompatible data requires review. |

Location ambiguity is deliberately conservative: labels containing `remote`,
`hybrid`, `onsite`, `anywhere`, `worldwide`, `multiple`, `various`, `tbd`, or `unknown`,
and alternatives separated by `/`, `;`, `|`, or ` or ` require review. A remote label
alone never establishes worldwide eligibility. `Remote - US only` remains unresolved;
this version does not parse geographic eligibility from prose. A concrete matching
preferred location passes even if another preference is ambiguous; otherwise an
ambiguous preference requires review. Commas are retained as part of a single
location, such as `Seattle, WA`.

Applicant `minimum_salary` and job `salary_min`/`salary_max` use `salary_currency`
and **`salary_period`**. Accepted applicant periods are `hourly`, `weekly`, `monthly`,
`annual`, or null, normalized for case and surrounding whitespace. For example:

```json
{"minimum_salary": 120000, "salary_currency": "USD", "salary_period": "annual"}
```

Job fixture JSON accepts the same `salary_period` field. Unknown or omitted job
periods require review when salary matters. Old records and older fixtures have
unknown periods; their amounts are never silently treated as annual. No conversion
is made between hourly, weekly, monthly, and annual amounts. A missing salary
threshold imposes no salary check, even if currency/period are configured.

## History and metrics

Each new deterministic evaluation links a job and applicant and stores its decision,
all check reasons, UTC evaluation time, rules version, and a JSON input snapshot.
The snapshot contains the applicant's remote/location/role/salary preferences and
the job's title, company, location, work arrangement, and compensation, plus both IDs.
This is enough to explain the decision after records change without copying contact
information. AI score, model-name, and cost fields remain null. Shared job status is
never replaced with an applicant decision.

A SHA-256 fingerprint covers that exact snapshot and rules version. Re-evaluating
an identical combination reuses the existing record, enforced by a unique database
index. Any change to a snapshotted value or the rules version creates another
historical evaluation. Reverting to a previously evaluated combination reuses that
older result. Contact details, skills (not checked in this version), and last-seen
timestamps do not affect the fingerprint. Whitespace/case edits may produce a new
snapshot even when the normalized decision stays the same.

`list` shows all historical results, newest first; its decision filter applies to
history, not just the latest result per job. Titles and companies come from the
saved snapshot for deterministic results. Legacy evaluations show their available
reason and are labeled with an unknown rules version.

Evaluation prints counts of newly kept, rejected, and review-needed results, plus
unchanged/skipped results. These counts are separate from ingestion `ProcessingRun`
metrics; deterministic evaluation does not increment `jobs_scored` or create a
processing run. Evaluation history itself is the durable audit trail. The CLI
commits the evaluation batch together and rolls it back on failure. Run one writer
at a time with SQLite; concurrent contention can return a database error for retry.

```powershell
python -m pytest -q --basetemp .pytest_cache/evaluation-tests
git diff --check
python -m alembic current
```
