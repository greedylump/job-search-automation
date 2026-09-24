# Job Search Automation

A small Python project for ingesting jobs from local fixtures, Remotive, and USAJOBS, normalizing them into a common model, storing them in SQLite, deduplicating them, and evaluating stored jobs against applicant preferences with explainable deterministic rules.

## Current state — September 22, 2026

The latest verified suite has **478 passing tests**. The migration head is
`20260920_18`. Shared applicant policy and editable A–D strategies are implemented
and privately configured locally. Conservative tier-aware deterministic evaluation
now records provisional routing, shared constraint checks, and unresolved review
items with complete policy snapshots. `tier-policy-v4` adds reusable rich evidence
and optional career-relevance signals to the requirement-to-evidence
gate and separates internally held records from prospective opportunities. Mandatory
mismatches cannot be rescued by a lower tier. See the qualification gate section
for supported grammar and the remaining promotion limitations.
The local database retains 141 jobs, 8 runs, and 5 request attempts. Multi-cycle
worker observation and deployment remain pending. See `LOCAL_OBSERVATION.md` for
the detailed checkpoint; dated sections below preserve earlier verification results.

## Project goal for v1

Jobs are shared source records. Ingestion rejects invalid source records and records `ProcessingRun` metrics. Applicant-specific decisions are stored separately in `JobEvaluation`; `Application` remains available for future tracking. AI scoring, employer contact, application submission, browser automation, and dashboards are outside this milestone.

## Project structure

```text
src/jobsearch/
    collectors/
    config/
    filtering/
    evaluation/
    ingestion/
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
    test_remotive_ingestion.py
    test_source_policies.py
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

## Live source: Remotive

For additional sources, request shapes, limits and collection planning, see the
[job API research catalog](JOB_API_RESEARCH.md).

The [Remotive public API](https://github.com/remotive-com/remote-jobs-api) provides
remote job listings without an API key. This adapter performs a single GET to
`https://remotive.com/api/remote-jobs`, with a 30-second socket timeout, a 20 MiB
response limit, and no automatic retries. It never visits application pages.
Remotive advises at most four fetches daily. A persistent source policy reserves
at least six hours between request attempts, including failed attempts. There is
no automatic response cache. Calls before the next eligible time are skipped.
HTTP `Retry-After` headers (seconds or HTTP dates) can extend the wait, never shorten
it. All workers for a source must share the same database; separate databases have
independent request budgets. Initialize/migrate the database before running workers
concurrently. SQLite serializes request reservations; normal job writes should
still use one writer at a time.

Run from the repository root (activation is optional):

```powershell
.\.venv\Scripts\python.exe -m jobsearch.scripts.run_remotive_ingestion --database-url sqlite:///./data/remotive-live.db --show 20
# Display matching titles without excluding other jobs from ingestion:
.\.venv\Scripts\python.exe -m jobsearch.scripts.run_remotive_ingestion --database-url sqlite:///./data/remotive-live.db --title engineer --show 10
```

`--database-url` is optional; otherwise `JOBSEARCH_DATABASE_URL` and the normal
default apply. The trial database above is separate from `jobsearch.db`. Repeating
the command during the interval records a skipped run with zero input/job counts,
a reason, and the next eligible UTC time. No HTTP request, normalization, or job
freshness update occurs. The CLI identifies live versus replay mode. `--title` and
`--show` affect display only; the full returned feed is ingested. Display lists
stored jobs, so it can include older listings that have since closed. This version
does not mark disappeared listings closed or refresh changed descriptions.

### Source policy and state

`JobSource` stores named collector instances with an adapter type, enabled flag,
validated JSON settings, endpoint, collection strategy, retention policy, and minimum
interval. The ORM model also persists request-attempt count, last attempt, last successful
fetch, last HTTP status, and next allowed request time. Source-state timestamps are
UTC (stored without timezone offsets for consistent SQLite comparisons).

Remotive selects `full_feed` with retention `none`. Incremental cursors, conditional
requests, and push/event sources can have their own adapters/policies later; they
are not implemented by this adapter. An unexpected HTTP 304 is recorded as
`not_modified`, with no job processing or timestamp refresh. No ETag is currently
sent. Stored policies must match the adapter; the minimum interval may be increased
but cannot be reduced below the adapter's minimum.

Request slots are committed before HTTP and survive process failure or job rollback.
`last_success_at` records a valid fetched response (or 304), not successful ingestion;
the separate processing run records ingestion success or failure. A failed request
does not erase the previous success timestamp. `request_attempts` counts reserved
attempts, so a crash between reservation and HTTP can consume a slot conservatively.
This interval policy bounds Remotive's requests; it is not yet a general token-bucket
or multi-window rate limiter.

### Explicit snapshots and replay

Normal collection neither reads nor writes response files. To retain a response for
debugging or recovery, explicitly choose a new snapshot filename:

```powershell
.\.venv\Scripts\python.exe -m jobsearch.scripts.run_remotive_ingestion --database-url sqlite:///./data/remotive-live.db --snapshot data/snapshots/remotive-response.json --show 0
.\.venv\Scripts\python.exe -m jobsearch.scripts.run_remotive_ingestion --database-url sqlite:///./data/remotive-live.db --replay data/snapshots/remotive-response.json --show 0
```

Snapshots are only written after an eligible, valid fetch; existing files are never
overwritten. Replay makes no HTTP request and does not advance request state or
existing jobs' `last_seen_at`. It can recover missing jobs; new rows' seen timestamps
then reflect replay/import time, not a fresh observation at the source. Runs have
`collection_mode=replay` so reports can exclude these from live throughput. Snapshots
are user-managed; the opt-in storage maintenance command below can expire them. `data/snapshots/`, legacy
`data/cache/`, and SQLite files are Git-ignored. Old cache files remain untouched and
are ignored by normal collection; they may be supplied explicitly to `--replay`.

Both collectors share `ingestion/pipeline.py`, including deduplication, source
validation, rollback, and rejection metrics. IDs are stored under the configured
instance name (`remotive` for the convenience command), independently of fixture IDs.
Overlapping listings from differently named instances are currently separate jobs;
cross-instance deduplication is not implemented. Titles, companies, employment type,
publication dates, geographic restrictions, plain-text descriptions, and Remotive
links are mapped to `Job`. All feed jobs are labeled remote, but that does not
establish worldwide eligibility. Publication dates without offsets remain naive;
the adapter does not invent a timezone. Salary text is preserved in the description,
while numeric salary, currency, and period fields remain null. Salary evaluation
therefore requires review when an applicant has a minimum salary requirement.
No direct application URL, AI score, or applicant fit is inferred.

Remotive requires source attribution and links back to its listings, prohibits
republishing to third-party job boards, and states that API listings are delayed
by 24 hours. See its [source terms](https://remotive.com/remote-jobs/api). The public
response may be small; it is not a complete inventory of remote opportunities.
`data/remotive_sample.json` is fictional test data. Automated tests mock HTTP and
never contact the real API.

### Live verification — 2026-09-14

Under the initial cache-based implementation, one API request returned 16 listings.
The first run stored 16 new jobs with zero
invalid records; a cached replay recorded 16 duplicates and zero new jobs. Both
runs completed with zero AI cost and zero jobs scored. Listings spanned software
development, DevOps, QA, IT, marketing, writing, sales, and other categories.
This verifies collection and storage, not applicant suitability or employer-side
availability. Local trial results remain in `data/remotive-live.db`.
The full suite passed **171 tests**, including offline HTTP/cache/error cases,
normalization, source isolation, rollback, and attributed evaluation output.
The live trial database passed integrity, foreign-key, and Alembic schema checks;
no schema migration or extra runtime dependency was needed for this source.
That checkpoint is historical: automatic cache replay was subsequently removed.

### Source-policy checkpoint — 2026-09-15

Automatic cache replay has been replaced by persistent request reservations and
skipped-run accounting. Full regression suite: **184 passed**. After the final
zero-cost skip adjustment, all **47 focused policy, Remotive, and ingestion tests**
passed. Tests cover interval boundaries, concurrent reservation attempts, network
and response failures, `Retry-After`, HTTP 304, migration preservation, and explicit
replay without updating existing job freshness. These checks use temporary databases
and mocked HTTP; no additional live API request was made for this change.

That checkpoint used migration `20260914_09`. Existing local databases receive migrations on
their next normal initialization/ingestion command. Historical cache files are not
deleted or replayed automatically. No new runtime dependency is required.

## Database-backed collectors

`collectors/adapters.py` defines the `CollectorAdapter` Python Protocol: validation,
collection, and normalization into `Job`. Implementations can have custom methods;
they do not need to inherit a common base class. A small trusted registry maps adapter
types to code. Instances and their mutable configuration live in `job_sources`, so
adding another instance of a supported adapter requires no code change.

`ingestion/runner.py` loads configured instances and uses the shared ingestion pipeline.
`collectors/http_client.py` handles bounded HTTP reads, error/backoff recording, and
explicit snapshots. `SourceRepository` handles atomic reservations and configuration
updates. All Remotive instances in one database share a request budget, including
disabled instances' outstanding waits. Adding an instance cannot bypass that budget.

Save this example as a JSON configuration file, such as `data/private/collector.json`:

```json
{"name": "sample-jobs", "adapter_type": "json_fixture", "settings": {"path": "data/jobs_fixture.json"}}
```

Run commands from the repository root; fixture paths are relative to the working directory:

```powershell
python -m jobsearch.scripts.collectors_cli create --input data/private/collector.json
python -m jobsearch.scripts.collectors_cli list
python -m jobsearch.scripts.collectors_cli status --limit 10
python -m jobsearch.scripts.collectors_cli status --name remotive --limit 5
python -m jobsearch.scripts.collectors_cli run --name sample-jobs
python -m jobsearch.scripts.collectors_cli run --all
```

For a Remotive instance, use `adapter_type: "remotive"` and optional settings such as
`{"search": "python", "category": "software-dev"}`. Adapter defaults supply the public
endpoint and minimum six-hour interval. These settings filter the API request itself.
Currently supported types are `remotive` and `json_fixture`.

Update an instance using a partial JSON file, for example `{"enabled": false}`:

```powershell
python -m jobsearch.scripts.collectors_cli update --name sample-jobs --input data/private/collector-update.json
```

Omitted fields remain unchanged; supplied `settings` replaces the entire settings
object. Names, adapter types, and request history cannot be edited through this API.
Invalid updates roll back. Intervals may be increased; existing waits are never
shortened. An optional `--database-url` goes before the subcommand.

`run --all` makes one pass over enabled rows, trying never/least recently attempted
instances first so shared budgets do not always favor the same instance. Failures
are reported without blocking other instances. This is not a background scheduler.
The original fixture and Remotive commands remain available and bootstrap their
default configuration rows; the fixture command updates its configured input path.
Normal collection uses no response cache.

`status` displays enabled flags, the shared adapter budget's next eligible UTC
time, total reserved attempts, and unfinished attempts with unknown outcomes.
It shows recent HTTP results, backoff deadlines, linked ingestion counts, and
recent runs (including skips and replays without HTTP). `--limit` accepts 1-100
and bounds each collector's recent attempts and runs separately. The unfinished
count includes older attempts outside that limit. A disabled collector stays
disabled even after its wait expires. The command makes no HTTP requests, but
like other management commands it initializes/migrates the selected database.

Status verification (2026-09-15): **209 tests passed**. After a SQLite backup to
`data/backups/remotive-before-status-verification.db`, the trial database
`data/remotive-live.db` migrated from `_08` to `_11`. One live request at
17:08 UTC returned HTTP 200 and 15 listings: 0 new, 15 duplicates, 0 invalid.
Attempt 1 links to completed run 3. The immediate repeat recorded skipped run 4
without another attempt; next eligible time was 23:08 UTC. Historical runs remain
labeled unknown mode. This database is still the local trial database, not a
deployed or merged production database.

Migration `20260915_10` adds the configuration columns and preserves existing request
history. Legacy source rows receive the Remotive adapter, enabled status, and empty
settings. No additional runtime dependency is required.

Verification on 2026-09-15: **198 tests passed**, covering configuration validation,
CLI management, multiple instances, shared request budgets and rotation, failure
isolation, and migration upgrade/downgrade preservation. Tests used temporary
databases and mocked HTTP; no additional live API request was made.

## Configuration

### Shared HTTP request execution

Migration `_13` adds nullable method, purpose, sanitized pagination metadata,
response bytes and returned-record counts to `RequestAttempt`. Existing attempts
remain unchanged with unknown values for the new fields.

HTTP adapters call `fetch_records` with a `build_request(config)` callback returning
a `RequestSpec` and a decoder returning a record list. The client loads current
configuration, checks permission, constructs the request, and atomically reserves
budget plus a ledger row before sending. Remotive no longer reserves requests itself.
Every call to the client, including a future page, detail, taxonomy or explicit retry,
must get a fresh reservation. There are no automatic retries. The production opener
does not follow redirects: a 3xx is recorded without an unbudgeted second request.

Metadata retains numeric page/offset/skip/limit/count values and hashes opaque cursor
values. Other query values, authentication headers and raw cursor values are omitted.
Trusted adapters must keep secrets and sensitive data out of URL paths, which are
recorded without query strings. Request purpose is `list`, `detail` or `taxonomy`.
Transport/HTTP errors suppress raw exception details that could contain credential
URLs. Decoder errors are recorded as invalid responses without retaining body text.
The shared client enforces response-size limits before decoding; status output shows
the new metadata and response metrics. Byte counts represent bytes read, including
the extra byte used to detect oversized responses, not necessarily full body size.

This centralizes requests for the current adapter and defines the path future
adapters must use; it is not a sandbox preventing trusted Python code from opening
its own sockets. Bounded pagination and the opt-in worker are described below.
No new live request was made
for this change and existing local databases were not migrated during testing.

### Collector schedules and shared budgets

Migration `_12` separates refresh scheduling from HTTP quotas. `JobSource` now
stores `refresh_interval_seconds`, `next_due_at`, `last_complete_refresh_at`, and
its assigned `budget_name`. `RequestBudget` holds shared request spacing and
backoff; `RequestBudgetWindow` holds rolling-window quotas. Request attempts link
to the budget they consumed. Remotive instances always use the `remotive` budget;
collector configuration cannot change this assignment to bypass limits.

Set a board's refresh interval through the existing collector update command with
JSON such as `{"refresh_interval_seconds":43200}`. This affects that board alone.
Successful ingestion or a single-response 304 advances the complete-refresh time.
Partial/failed runs defer the next attempt without marking a complete refresh;
replay leaves the schedule unchanged. New instances default to zero additional refresh delay; their HTTP
budget still applies. Migrated HTTP instances use their prior request interval as
their refresh interval, but unknown historical completion times remain null.

Update an existing shared budget with:

```powershell
python -m jobsearch.scripts.collectors_cli budget-update --name remotive --input data/private/budget.json
```

Example budget input (replaces its configured rules):

```json
{"min_interval_seconds":21600,"windows":[{"window_seconds":86400,"max_requests":4}]}
```

All windows apply together. They are rolling durations, not calendar-day/month
reset rules. Each committed reservation consumes quota even if HTTP fails or its
outcome is unknown. The count uses durable request history across every board in
the budget. Do not purge ledger history needed by active windows. Remotive spacing
cannot be reduced below six hours. Updates preserve existing spacing/backoff and
active window waits. The old collector `min_interval_seconds` setting remains a
compatibility control that can only increase shared spacing; prefer `budget-update`
for shared policy and `refresh_interval_seconds` for board scheduling.

Migration preserves old collector/attempt fields and copies the longest outstanding
wait (including disabled collectors) and strictest spacing into each shared budget.
It does not fabricate missing request history or enable new quota windows. Existing
collector request-state fields remain compatibility/history fields; shared budgets
are now authoritative for HTTP permission. `status` reports both schedule and budget.

Future adapters
must select their trusted budget scope; arbitrary account/IP budget assignment is
not exposed yet. The migration was tested on temporary databases; local live
databases are upgraded on their next initialization command.

### Bounded pagination and opt-in collection worker

Migration `_14` adds durable continuation state, collector lease fields, and nullable
`ProcessingRun.pages_collected`. Existing history is preserved. Nothing starts
automatically after installing or migrating the project.

```powershell
# One pass over due, enabled live collectors:
python -m jobsearch.scripts.collection_worker --database-url sqlite:///./data/remotive-live.db --once
# Foreground worker, explicitly enabled; Ctrl+C stops after the current bounded run:
python -m jobsearch.scripts.collection_worker --database-url sqlite:///./data/remotive-live.db --loop --poll-seconds 60 --max-collectors 20
```

These commands can make real requests. The worker excludes fixture adapters, checks
board schedules and shared budgets, and rechecks eligibility between collectors.
It uses one serial worker by default, polls no faster than once per minute, and
handles SIGINT/SIGTERM without starting another collector. No operating-system
service is installed. Configure a positive board refresh interval for future feeds;
zero means the board itself imposes no delay beyond polling and its HTTP budget.

`PaginatedAdapter` is an optional mixin for future paginated sources. Implement its
`build_page_request(config, cursor)` and `decode_page(raw)` returning a `Page`, plus
the usual validation/normalization/defaults contract. It uses the shared HTTP client
for every page. Default bounds are 5 pages, 10,000 records and 20 MiB per response;
adapter overrides allow at most 100 pages and 100,000 records per run. Response-size
limits still apply separately to each request. Repeated cursors stop the run.

Resume is off by default: the next run restarts at the beginning and deduplicates.
An adapter must explicitly set `resume_safe=True` only when its API guarantees a
stable continuation. Mutable offset feeds may skip jobs when resumed; do not opt
them in without such a guarantee. Remotive remains a single-response feed and does
not invent pagination. The pagination path is verified with a mocked test adapter;
no additional live provider was installed as part of this milestone.

Successful pages and the continuation checkpoint commit together with run metrics.
If more pages remain, status is `partial`; if no pages were accepted, `deferred`.
Budget waits, page/record caps and later-page errors never mark the board completely
refreshed. Continuation is delayed by at least five minutes and any provider wait.
A first-page failure remains `failed` and is also deferred at least five minutes.
There is no immediate HTTP retry. A record cap never saves a cursor past a discarded
page. Ingestion rollback leaves the previous checkpoint intact; HTTP history remains.
Completion clears the checkpoint and advances the board's refresh schedule atomically.
No absent listing is marked closed. Adjust insufficient page caps before relying
on a full refresh of a large source that cannot safely resume.

Collectors use atomic five-minute leases, renewed before each HTTP request. An
expired owner cannot reserve more requests or commit ingestion; a later run can
recover after expiry. Interrupted HTTP attempts retain unknown outcomes. This
does not cancel an already-running socket operation. Configuration changes other
than enable/disable are rejected during a live lease; changing endpoint/settings
afterward clears old continuation state. Replay also claims a lease but does not
advance live checkpoints. Use one worker with SQLite; leases additionally guard
against accidental overlapping invocations.

Status displays whether continuation exists without exposing its value. Raw opaque
continuations are operational state in the private database; attempt metadata still
stores only cursor hashes. Keep the database and its backups private during transfer
to the VPS. No daemon or live fetch was started to verify this implementation.

Verification: full suite **226 passed**, followed by **27 focused tests passed**
after the final partial-run backoff and CLI redaction adjustments. Tests cover
resume, rollback, quota exhaustion, page failure, cursor loops, expired leases,
due-only selection and worker shutdown with temporary databases and mocked HTTP.

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

The migration chain in `alembic/versions/` should produce a head revision of `20260920_18` and the `jobs` table must expose the unique `source + source_job_id` index shape recorded in the model.


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
over both. The final migration head is `20260920_18`: `_03` retains its historical
`completed` default, `_04` adds applicants and nullable links, and `_05` changes
only the default for new processing runs to `running`, preserving existing statuses.
`_06` adds nullable salary periods and versioned deterministic evaluation history.
Existing salary periods remain unknown; existing evaluations and nullable legacy
applicant links are preserved.
`_07` renames `jobs_seen` to `records_seen` and `jobs_filtered` to
`records_invalid`, preserving historical values without recalculating them.
`_08` adds nullable `invalid_reason_counts`; historical breakdowns remain unknown.
`_09` adds source policies/request state and nullable run-mode/skip fields. Historical
run modes remain unknown. If historical Remotive runs exist, the migration initializes
a conservative next-allowed time six hours after the latest run, without inventing
HTTP attempt/success times. Request-attempt counting starts with the new tracking.

`_11` adds `request_attempts`, linked by foreign key to each processing run and
collector. A reservation and its rate-limit update commit together before HTTP.
Each row retains the base endpoint (without query parameters or credentials),
reservation/completion times, outcome, HTTP status, parsed retry deadline, and the
next allowed time at completion. Outcomes include `success`, `http_error`,
`network_error`, `invalid_response`, and `not_modified`. An unfinished `reserved`
row means the outcome is unknown; it does not prove a request reached the server.
Request results survive subsequent ingestion rollback. Skips, fixtures, and replay
create no HTTP attempt rows. Direct low-level reservations create a parent run in
`request` mode; normal ingestion links attempts to its existing `live` run.

Historical HTTP attempts are not reconstructed from old runs or aggregate counts.
The ledger moves with the SQLite database during backup/deployment; copying code
alone does not transfer it. All live workers must continue sharing one request
budget database. This change was verified with the existing 198-test regression
suite and six new request-ledger tests, using temporary databases and mocked HTTP.

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

This checkpoint completed fixture ingestion. The subsequent Remotive milestone
above adds a real source with conservative collection and error handling.
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

### Applicant policy and tier configuration — milestone 1

Verified September 18, 2026: **265 tests passed**. The backed-up local database is
at `20260918_17`, with one privately configured applicant, policy revision 1, and
four enabled A–D strategies. SQLite integrity and foreign-key checks passed.
Existing jobs and request history were preserved; no live API calls were made.

Migration `20260918_17` adds `search_policies` (one row per applicant) and
`tier_strategies` (one unique A/B/C/D row under that policy). Existing applicants,
jobs, evaluations, and applications are unchanged. No collection request or
evaluation is performed by configuration commands. Policy definitions use a
validated version-1 JSON schema; the human-editable example is
`data/search_policy_sample.json`, which contains fictional data only.

Policies store OR alternatives for work arrangement/country/region, relocation
handling, employment types, exclusions, reported citizenship/credentials, and
independent scoring dimensions. Unknown information remains review-needed; a
credential list marked incomplete is not evidence that unlisted credentials are
missing. Region names are configuration labels at this stage, not implemented
geographic matching. Compensation has no global salary floor. Strategy definitions
store role examples, guidance, tailoring level, compensation guidance, and an
optional application-time cap. Null caps mean unspecified, not zero minutes.
Roles may overlap between tiers; provisional routing is now implemented below.
Application submission remains future work.

```powershell
# One-time import: bundle contains applicant, policy, and strategies.
python -m jobsearch.scripts.policy_cli --database-url sqlite:///./data/remotive-live.db import --input data/private/applicant-policy.json
python -m jobsearch.scripts.policy_cli --database-url sqlite:///./data/remotive-live.db view --applicant-id 1
# Change one strategy using its complete tier/name/enabled/definition object.
python -m jobsearch.scripts.policy_cli --database-url sqlite:///./data/remotive-live.db strategy-update --applicant-id 1 --expected-revision 1 --input data/private/strategy-edit.json
```

Use the applicant ID returned by import rather than assuming ID 1. Import without
`--applicant-id` explicitly creates a new applicant; do not use it to update one.
To replace an existing policy, supply `--applicant-id` and `--expected-revision`,
with a JSON object containing only `policy` and all four `strategies`. This does
not edit applicant identity or qualifications. Use the existing applicant CLI for
those fields. Import and edits are atomic. CLI writes acquire the SQLite write
lock, and stale revisions are rejected. A changed policy or strategy increments
the shared revision; identical re-imports do not. Strategy IDs remain stable.
Nested definitions are replaced through repository methods rather than mutated
in place. Disabled strategies retain their rows. This revision counter does not
archive every configuration edit; evaluation snapshots now preserve the configuration
used for each distinct evaluation. Downgrading migration 17 removes policy/strategy configuration, so
back up before doing so.

Applicants with a saved policy now use `tier-policy-v3`. Applicants without a
policy retain `preferences-v1`; historical evaluations remain readable. The
policy evaluator does not apply legacy target-role lists or a global salary floor.
Collection remains independent of applicant filtering.

### Tier-aware evaluation — milestone 2 (September 18 checkpoint)

Verified September 18, 2026: **288 tests passed**, including 23 new tier tests.
Fresh/upgrade migration tests passed. A temporary backup of the local database
passed schema comparison, integrity and foreign-key checks, replay of all 116
evaluations, and repeat-evaluation idempotency. All 116 required review and had no
configured title-phrase match. This demonstrates conservative preservation, not
useful routing coverage for that sample; aliases or richer reviewed evidence are
needed before claiming broad coverage. The live database was opened read-only and
still contains zero evaluations. Temporary verification copies were removed.

Use an explicit database target; evaluation reads stored jobs without collecting:

```powershell
python -m jobsearch.scripts.evaluation_cli --database-url sqlite:///./data/review-copy.db evaluate --applicant-id 1
python -m jobsearch.scripts.evaluation_cli --database-url sqlite:///./data/review-copy.db list --applicant-id 1
```

Use the actual applicant ID and an already populated database. The command migrates
the selected database and writes evaluation history. This milestone requires no
schema change; head remains `20260918_17`.

Known work arrangements must match at least one shared location alternative's
arrangements. Recognized employment types are checked against the shared allowed
list; explicit `c2c` rejects when excluded. Generic contract/consulting with a C2C
exclusion requires review because it does not identify W-2 terms. Unknown values
require review. All checks run even after a definite conflict, and rejection wins.

Enabled strategies match case/whitespace-normalized whole phrases in the title.
Punctuation is literal; synonyms and experience levels are not inferred. All
matching tier/role pairs are retained in reasons and printed by the CLI. A–D
precedence selects a **provisional** tier and its tailoring guidance when roles
overlap. This ordering is an explicit routing convention, not a fit ranking.
No match leaves the tier unassigned and requests review, including when every
strategy is disabled. D is not a catch-all for unmatched titles. Rejected jobs can
retain a provisional tier for audit; that tier never overrides rejection.

Free-text location is not a verified country, metro boundary, commute, or remote
eligibility fact. Geography and relocation remain review items. Clearance, physical
demands, citizenship eligibility, and mandatory credentials also require review:
this version does not extract binding requirements from prose or treat missing
keywords as clearance to proceed. It never assumes unlisted credentials are absent.
These limitations mean policy results are currently **review or reject, never
automatic keep**. A provisional tier is useful for organizing human review, not
proof that an application is worthwhile or that the applicant is qualified.

Hireability, career value, income value, and application friction each have a
separate reason. Numeric scores remain null. Reported pay is retained without a
global floor, annualization, currency conversion, or invented market comparison.
Strategy compensation guidance and any application-minute cap are carried into
reasons, but free-text value guidance and unknown application time require judgment.
A minimal-tailoring strategy or application link does not prove a cheap application.
No AI call, platform interaction, resume generation, or application is performed.

Each evaluation snapshots the shared policy revision and complete definition, all
four strategies (including disabled ones), applicant location/skills/experience
summaries, and relevant job fields including description, source links, employment
and pay. Contact details are omitted. These snapshots are private applicant data.
The existing fingerprint and unique index reuse identical inputs; policy revisions,
strategy edits, relevant profile/job edits, and rule-version changes create history.
`tier_rules.evaluate(saved_input_context)` reproduces results using the matching
rule implementation. Retain versioned source code when changing rule versions.
Policy edits never rewrite prior snapshots. Ingestion metrics and shared job rows
are untouched, and the CLI rolls back the whole evaluation batch on failure.

Real applicant input belongs under Git-ignored `data/private/`, and the SQLite
database is also ignored. These are plaintext private files; ignored by Git does
not mean encrypted. `policy_cli view` intentionally displays private preferences
locally; do not publish its output. Public aggregate metrics contain none of these
profile/policy definitions.

### USAJOBS local collector

The `usajobs` adapter uses the official authenticated Search API. Credentials are
loaded at request time from `JOBSEARCH_USAJOBS_API_KEY` and
`JOBSEARCH_USAJOBS_EMAIL` in the environment or ignored project `.env`. They are
sent only in headers, never saved in collector settings or request metadata.
The endpoint is fixed to HTTPS `data.usajobs.gov`; automatic redirects remain
disabled. Do not place credentials in the example configuration files.

```powershell
python -m jobsearch.scripts.collectors_cli --database-url sqlite:///./data/remotive-live.db create --input data/usajobs_collector.json
python -m jobsearch.scripts.collectors_cli --database-url sqlite:///./data/remotive-live.db budget-update --name usajobs --input data/usajobs_budget.json
python -m jobsearch.scripts.collection_worker --database-url sqlite:///./data/remotive-live.db --once
```

Create is a one-time operation. Change an existing instance with `update --name
usajobs --input <partial-config.json>`; omit `name` and `adapter_type` from updates.
The sample searches public IT-series `2210` announcements, no geographic filter,
newest opening dates first, full fields, 100 records per page, and **one page per
refresh** for initial observation. It refreshes every six hours. `settings.query`
supports Keyword, PositionTitle, JobCategoryCode, LocationName, Organization,
DatePosted (0–60 as a string), RemoteIndicator (`"True"`/`"False"`), and HiringPath.
`settings.page_size` is 1–500 and `settings.max_pages` is 1–20. Filters describe a
search, not an assertion that the applicant is eligible for federal employment.

Each page uses the shared HTTP ledger, budget checks, storage guard, and 20 MiB
response bound. Pages are paced at least two seconds apart. The example budget is
**our conservative local policy**, not a claimed USAJOBS quota: two-second spacing,
60 requests/hour, and 200/day across USAJOBS instances in this database. Configure
the example budget before running the example collector. API 429/Retry-After stops
the batch without immediate retry. USAJOBS documents 500 rows/page and 10,000/query,
but no numeric request/time quota in the reviewed rate guide.

Page numbers do not provide a stable snapshot, so interrupted or capped batches
restart at page one and deduplicate on their next refresh; they do not persist an
unsafe page cursor. Partial results remain marked partial and wait at least six
hours, avoiding repeated first-page polling every five minutes. Increase page
coverage or narrow search criteria when a cap prevents full coverage. No historical
backfill completeness is claimed. Jobs use MatchedObjectId as source ID and preserve
the supplied application link and posting-channel attribution. Telework does not
imply remote; unspecified currency remains unknown, and recognized pay periods
are normalized without annualizing. Closing dates and eligibility text are retained
in description text; application eligibility filtering is future work.

Official references: [authentication](https://developer.usajobs.gov/guides/authentication),
[search fields](https://developer.usajobs.gov/api-reference/get-api-search), and
[result limits](https://developer.usajobs.gov/guides/rate-limiting).

Local verification, September 17, 2026: **251 tests passed**, including mocked
multi-page requests, deduplication, caps, missing credentials, malformed responses,
and 429/backoff with no credential logging. A backed-up live database was used for
one worker sweep at approximately 21:43 UTC. USAJOBS returned HTTP 200 and 100 new
jobs (one page, partial due to the explicit cap); Remotive returned HTTP 200 and
15 duplicates. Neither run rejected records. Database size increased from 200,704
to 974,848 bytes (774,144 bytes growth), for 116 stored jobs total. USAJOBS response
size was 2,175,675 bytes; only normalized job data and request metrics were stored.
An immediate second sweep added no requests or runs. Integrity/foreign-key checks
passed, and exact credential values were absent from the database and worker logs.
Both sources next become due around September 18, 03:43 UTC (September 17, 10:43 PM
Central). These are historical observation times, not instructions to bypass the
database schedule. No background worker was left running. Multiple refresh cycles
are still needed to measure sustained yield and growth; no deployment was performed.

### Storage protection and retention (September 16 checkpoint)

Checkpoint review: **237 tests passed**. A separate-process CLI walkthrough using
a fresh temporary SQLite database verified fixture ingestion, persistent manual
pause, blocked ingestion, explicit resume, and deduplication after resumption.
Both app-size and free-disk thresholds refused unsafe resume and remained paused
after thresholds recovered until explicitly resumed. Alembic reported
`20260916_15 (head)`; integrity and foreign-key checks passed, with zero HTTP
attempts. Review also added the global pause reason to collector status and fixed
snapshot maintenance's rejection of relative paths resolving to a filesystem root.
Existing live databases and VPS configuration were not changed by verification.

Migration `20260916_15` adds a singleton `collection_control` row. Collection pauses
survive process restarts and deployment when the database is transferred. No service
is installed or started by this change. Existing databases are upgraded when an
application command runs migrations; tests use temporary databases.

The following environment settings are tunable (decimal bytes, not GiB):

| Setting | Default |
| --- | ---: |
| `JOBSEARCH_STORAGE_MAX_BYTES` | 8000000000 (8 GB) |
| `JOBSEARCH_STORAGE_WARN_BYTES` | 6000000000 (6 GB) |
| `JOBSEARCH_DISK_MIN_FREE_BYTES` | 5000000000 (5 GB, independent of app usage) |
| `JOBSEARCH_DISK_WARN_FREE_BYTES` | 7000000000 (7 GB) |
| `JOBSEARCH_LOG_MAX_BYTES` | 100000000 (approximately 100 MB across 10 files) |
| `JOBSEARCH_SNAPSHOT_RETENTION_DAYS` | 7 |

Accounting includes all regular files beneath `JOBSEARCH_DATA_DIR` (default `data`),
the selected SQLite database and its WAL/SHM/journal companions, and additional
directories in `JOBSEARCH_STORAGE_DIRS` (a JSON array of paths). Put backups and
generated documents in these directories. Overlapping directories count files once.
Do not include the whole VPS or repository as an app directory. Symlinks within
tracked directories cause a fail-closed pause; configured roots themselves resolve
to their targets. Free space is checked on storage destinations and filesystems
encountered during accounting. Untracked files still consume filesystem free space.
Snapshots must be written inside a tracked directory.

Checks run before collection, each HTTP request, and batch persistence. Breaches or
unreadable storage latch a global pause. Explicit ingestion records `status=paused`
and the reason in `skip_reason`; the worker does not create skipped runs every poll.
An in-flight request may finish and retains its attempt ledger. If a batch cannot
be saved safely, no jobs or continuation checkpoint from that batch are committed;
resume re-fetches from the prior checkpoint, subject to normal provider budgets.
Already committed batches remain intact. Warnings log on entering a warning state
within a process; pause/resume transitions are logged. These checks are not a hard
filesystem quota: concurrent writers and a batch can overshoot between checks.
Use one worker and leave operational headroom. Metadata writes are still needed
to record pauses; a completely full disk can prevent even those writes.

```powershell
python -m jobsearch.scripts.storage_cli --database-url sqlite:///./data/remotive-live.db status
python -m jobsearch.scripts.storage_cli --database-url sqlite:///./data/remotive-live.db pause
python -m jobsearch.scripts.storage_cli --database-url sqlite:///./data/remotive-live.db resume
```

Status includes usage, thresholds, warning, and pause reason, and latches a detected
breach. Resume remeasures storage and refuses while unsafe (exit code 2 while
paused). Neither restart nor cleanup automatically resumes collection. Pauses also
block fixture/replay ingestion, but leave inspection and maintenance available.

The collection worker rotates `data/logs/collection.log` (or the configured data
directory). Console logs remain available; systemd journal limits are a separate
deployment task. Direct CLI commands currently log to the console only.

Snapshot maintenance is opt-in and **dry run by default**. It lists exact paths and
byte totals; `--apply` deletes only old regular `.json` files directly in the chosen
directory, never recursively, and skips symlinks. Use a dedicated disposable
snapshot directory, not an applicant-input or fixture directory.

```powershell
python -m jobsearch.scripts.storage_maintenance --snapshot-dir data/snapshots
python -m jobsearch.scripts.storage_maintenance --snapshot-dir data/snapshots --days 7 --apply
```

Database history retention is now available as an explicit maintenance command.
Defaults are 180 days for requests and 365 days for runs, tunable with
`JOBSEARCH_REQUEST_RETENTION_DAYS` and `JOBSEARCH_RUN_RETENTION_DAYS` or command flags.
The command migrates the schema if necessary but previews row deletion by default.
It lists exact IDs and date ranges, bounded to 1,000 eligible rows per table per
invocation (configurable up to 10,000). Re-run to process further batches.

```powershell
python -m jobsearch.scripts.history_maintenance --database-url sqlite:///./data/remotive-live.db
python -m jobsearch.scripts.history_maintenance --database-url sqlite:///./data/remotive-live.db --apply
```

Migration `20260917_16` adds `daily_metrics`. Applying retention adds each eligible
row to its UTC day/source/type/status group, then deletes the detail in the same
SQLite write transaction. Metrics include run counts, job counts, invalid reasons,
AI cost, pages, elapsed time, request outcomes/status/purpose, response bytes, and
records returned. Null fields have known-row counters and are not silently treated
as measured zero. Groups contain no request URLs, credentials, applicant profiles,
or descriptions. **These aggregates cover deleted rows only**: combine them with
retained detail to calculate lifetime totals, and keep request and run totals
separate. Repeated cleanup cannot count a deleted row twice. Detailed errors and
individual timings are no longer available once their retention period expires.

Unfinished requests, running parents, future retry/reservation deadlines, and
requests within any active rolling budget window are retained. Runs with retained
request children cannot be deleted. Enlarging a quota window into already-pruned
history is rejected because the precise request timestamps no longer exist.
Downgrading migration 16 with populated aggregates is refused to prevent losing the
only remaining history. Restore a pre-retention backup if rollback is necessary.
Job, applicant, application, and evaluation tables are never pruned by this command.
No automatic VACUUM runs: SQLite normally reuses freed pages rather than shrinking
the file, and compaction needs extra disk headroom. Scheduled maintenance, automatic
backup rotation, and systemd supervision remain future work.

### Expanded local observation

`data/usajobs_expanded.json` raises the existing IT-series collector to three pages
of 100 results each, retaining its query and six-hour refresh schedule:

```powershell
python -m jobsearch.scripts.collectors_cli --database-url sqlite:///./data/remotive-live.db update --name usajobs --input data/usajobs_expanded.json
python -m jobsearch.scripts.collection_worker --database-url sqlite:///./data/remotive-live.db --loop --poll-seconds 60 --max-runtime-seconds 66000
python -m jobsearch.scripts.observation_report --database-url sqlite:///./data/remotive-live.db
```

The bounded loop stops after about 18 hours 20 minutes, after finishing any current
batch. The PC must stay awake and connected; missed polling periods do not fabricate
historical runs. Ctrl+C stops a foreground loop. The persistent storage CLI `pause`
blocks further collection even if a loop remains running. Keep one worker per DB.
The report shows storage state, schedules, recent runs, retained attempts, and up to
100 archived metric groups. Worker logs rotate in `data/logs/collection.log`.
See `LOCAL_OBSERVATION.md` for the initial relevance review and observation limits.

Each new deterministic evaluation links a job and applicant and stores its decision,
all check reasons, UTC evaluation time, rules version, and a JSON input snapshot.
For `preferences-v1`, the snapshot contains the applicant's remote/location/role/salary preferences and
the job's title, company, location, work arrangement, and compensation, plus both IDs.
This is enough to explain the decision after records change without copying contact
information. AI score, model-name, and cost fields remain null. Shared job status is
never replaced with an applicant decision.

A SHA-256 fingerprint covers that exact snapshot and rules version. Re-evaluating
an identical combination reuses the existing record, enforced by a unique database
index. Any change to a snapshotted value or the rules version creates another
historical evaluation. Reverting to a previously evaluated combination reuses that
older result. For `preferences-v1`, contact details, skills (not checked in that version), and last-seen
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

## Auditable facts and availability — September 20

Verification: **334 tests passed**, including 46 facts/availability cases covering
timezone boundaries, evidence, ambiguous requirements, historical replay, and
read-only inspection. `git diff --check` passed.

`job_facts.extract` derives applicant-independent `job-facts-v1` facts from stored
job fields. It preserves raw values in the source record and records the field,
exact supporting text, and character offsets for each recognized fact. No schema
migration is needed; head remains `20260918_17`. Derived facts are recomputed for
inspection and saved inside new evaluation snapshots, not written over job records.

Inspect an existing SQLite file without migrations, applicant reads, or writes:

```powershell
.\.venv\Scripts\python.exe -m jobsearch.scripts.job_facts_cli --database data/remotive-live.db --summary-only
# Reproducible historical inspection; omit --summary-only to include evidence.
.\.venv\Scripts\python.exe -m jobsearch.scripts.job_facts_cli --database data/remotive-live.db --as-of 2026-09-20T12:00:00Z --job-id 31
```

The CLI opens SQLite with `mode=ro`; it does not create a missing database. The
default assessment time is current UTC; `--as-of` requires an explicit offset.
This command is distinct from `evaluation_cli`, which writes evaluation history.

Supported facts and limits:

- Employment: exact aliases such as `Full Time`, `full-time`, `Part Time`, W-2
  contract and C2C become canonical values. `Permanent`, freelance, missing data,
  and free-text hour ranges remain unknown; duration does not establish schedule
  or contractual terms. The original label is retained with evidence.
- Availability: for USAJOBS-normalized records, parse the single labeled
  `Application closes:` field. Offset-bearing ISO datetimes use their exact instant.
  Timezone-free datetimes use a conservative 24-hour guard on either side; date-only
  values additionally include the entire reported day. Results distinguish
  `before_reported_deadline`, `deadline_uncertain`, `past_reported_deadline`, and
  `unknown`. Invalid/multiple dates remain unknown. A future deadline does not prove
  the listing is open, and an old deadline does not establish that it was never
  extended. Other sources remain unknown. No URL is visited to verify availability.
- Requirements: within the USAJOBS-labeled Requirements section only, recognize a
  small set of complete affirmative sentences requiring Secret/Top Secret clearance
  or explicitly requiring an active clearance. Negated, conditional, example,
  potentially waived, public-trust, and unrecognized wording remain unresolved.
  Other sections and sources are not scanned for binding requirements. This is not
  comprehensive extraction of citizenship, licenses, credentials, or physical demands.

New `tier-policy-v2` results use canonical employment facts, reject past reported
deadlines with an explicit availability reason, and apply clearance exclusions only
to recognized requirements. A requirement to obtain clearance does not prove an
active clearance is required at application time. Availability stays a separate
reason from applicant eligibility and fit; shared job status and ingestion metrics
are unchanged. Title routing and the other unresolved review checks are unchanged.

Snapshots include fact version, evidence, availability state, and `facts_as_of`.
The fingerprint excludes only that assessment timestamp, so unchanged facts/state
reuse the original evaluation and its original assessment time. Crossing a deadline
state creates new history. The four value dimensions remain separate and unscored.
`tier_rules.evaluate` dispatches saved `tier-policy-v1` contexts to the retained v1
implementation, preserving old replay behavior. No live evaluations were written
to introduce these rules.

Local inspection at `2026-09-20T12:00:00Z`: 87 listings before their reported
deadline, 6 uncertain, 7 past, and 16 unknown. Four jobs have recognized clearance
evidence. A temporary-copy evaluation produced 8 distinct rejects (7 deadline and
4 clearance reasons, with overlap) and 108 review results. Replay, idempotency,
schema comparison, integrity, and foreign-key checks passed. The copy was removed;
live counts remain 116 jobs, 7 runs, 4 attempts, and zero evaluations.

Remaining operational limitation: ingestion currently refreshes existing jobs'
last-seen time without updating their descriptions or deadlines. New normalization
or extraction cannot recover source fields that were never retained. Source refresh
and expiry handling must be addressed before treating this as a current inventory.

## Qualification gate and prospective queue — September 20

Verification: **361 tests passed**, including 27 qualification-gate cases.
Tests cover both OR alternatives, branch mixing, commercial-year bounds, unknown
evidence, negation/waivers, title-only false positives, explicit job exclusions,
profile changes, migration preservation, rollback safeguards, and hidden held output.
Temporary-copy migration, schema, integrity, replay, and idempotency checks passed.

`tier-policy-v3` separates mandatory-requirement comparison from tier routing.
The durable `queue_state` has three values:

| State | Meaning | Treatment |
| --- | --- | --- |
| `do_not_pursue` | A known mandatory mismatch, explicit applicant exclusion, or hard constraint rejects the job | No assigned tier or tailoring; retain audit history |
| `unresolved` | Requirement coverage, applicant evidence, or shared constraints remain unknown | Internal holding; not a request for applicant review |
| `plausible` | Requirement evidence is supported and shared hard checks are resolved | May proceed to strategy/value assessment; not application authorization |

Policy `evaluate` output shows prospective records by default and counts held and
excluded records. Use `--show-all` for their audit details. `list` is explicitly
historical audit output, not a current shortlist. The legacy decision column is
retained for compatibility; use `queue_state` for the prospective workflow. Legacy
evaluations have null queue state and are not retroactively classified.

```powershell
python -m jobsearch.scripts.evaluation_cli --database-url sqlite:///./data/review-copy.db evaluate --applicant-id 1
python -m jobsearch.scripts.evaluation_cli --database-url sqlite:///./data/review-copy.db evaluate --applicant-id 1 --show-all
```

Applicant `experience_evidence` is a validated, nullable version-1 JSON object with
`skills` and `job_exclusions` lists. Each skill records an explicit commercial-years
lower bound, upper bound, optional expertise assertion, and supporting source text.
Null means unknown. A lower bound of five supports a three-year minimum; an upper
bound of two contradicts it. A lower bound of one with unknown upper bound does not
prove the applicant has less than three years. Project experience is not silently
converted into commercial tenure. Existing skill names and prose remain stored but
do not supply missing durations or expertise assertions.

Use the fictional `data/experience_evidence_sample.json` shape with the existing
applicant CLI update command against a chosen database. `view` includes the evidence.
Updates replace the entire evidence object, so preserve existing entries when editing.
Evidence and job-exclusion reasons are private applicant data; use `data/private/`.
An explicit exclusion identifies a source and source job ID plus the applicant's
reason. It records a declined job without inventing exact experience durations or
generalizing the decision to unrelated listings. No live profile update is automatic.

The first extraction grammar recognizes a labeled Requirements section containing
`Commercial experience: Skill: N+ years, Skill: M+ years OR ...` and affirmative
`Expertise in Skill, Skill and Skill is a must.` sentences. Comma/AND clauses form
conjunctions; OR branches remain separate. Skill aliases are limited to explicit
React.js/React, Node.js/Node, and Next.js/Next spellings. Evidence retains exact source
spans. Advertising after recognized benefit/other-opportunity boundaries is excluded.
Unparsed text prevents a fully supported result; ambiguous alternatives, preferences,
waivers, and recognized negation prevent confident mismatch classification. This is
not a general natural-language parser. General experience durations, credentials,
recency, and most job-description formats remain unsupported.

AND fails when a known required clause fails. OR fails only when every branch fails;
unknown branches stay unknown. Years from different OR branches cannot be combined.
A title match is retained only as an audit candidate when the gate fails or holds;
the assigned tier and tailoring are null. Changing applicant evidence, exclusions,
job inputs, or rule versions creates a distinct snapshot. Saved v1/v2 rule contexts
still replay through their retained implementations.

Migration `20260920_18` adds nullable applicant evidence and evaluation queue-state
columns, preserving existing rows. Downgrade refuses populated applicant evidence
because it has no guaranteed historical copy. After offline migration verification,
the live database was backed up and migrated on September 21.

Current limitation: existing geography/eligibility checks still require review, so
this milestone does not automatically populate the prospective queue. The gate's
supported comparison path is tested, but resolving shared constraints and broadening
extraction require further work. It must not promote jobs merely because none were
proven impossible. Value dimensions remain separate; human review prioritization,
AI classification, and application automation are not implemented.

## Reusable requirement-parser profiles — September 21

Verification: **374 tests passed**, including 13 parser-profile tests covering
non-software careers, different applicants, validation, CLI selection, history,
and replay. The 40 focused parser/qualification tests also passed.

The parser's headings, section boundaries, clause patterns, AND/OR separators,
negation/ambiguity conventions, and skill aliases are now supplied as a validated
JSON profile. The shared engine constructs requirement trees, preserves source
spans and incomplete coverage, and compares evidence without career-specific
branches. Profiles describe language/vocabulary conventions, not an applicant.

Examples: `data/requirement_parser_software.json` preserves the existing conventions;
`data/requirement_parser_accounting.json` uses professional-experience headings and
an accounts-payable alias. The same engine is tested with fictional accounting and
nursing requirements and different applicants. This demonstrates reuse of the
supported grammar, not comprehensive coverage of those occupations.

```powershell
python -m jobsearch.scripts.evaluation_cli --database-url sqlite:///./data/review-copy.db evaluate --applicant-id 1 --parser-profile data/requirement_parser_accounting.json --show-all
```

In Python, use `extract_requirements(job, profile)` and
`assess(job, applicant_evidence, requirements)`. Direct tree comparison accepts
`compare(tree, applicant_evidence, profile)`. The repository accepts the same
dictionary through `evaluate_jobs(..., parser_profile=profile)`. Explicit profiles
are rejected for legacy applicants without a tier policy rather than silently ignored.

Profile schema 1 requires `name`, positive `revision`, `aliases`, `patterns`, and
`schema_version`. Supply all patterns shown in the examples. `years_clause` captures
skill name then numeric years; `expertise_clause` captures the skill list. All other
patterns use noncapturing groups. Aliases map normalized names directly to canonical
names; chains/cycles are rejected. Regex syntax, capture counts, and empty-string
matches are validated. Patterns are trusted local configuration, never accepted
from a listing; they are not a sandboxed grammar language.

`qualification-v2` extraction snapshots the complete profile along with the parsed
tree. Profile content changes create distinct evaluation fingerprints even when an
editor forgets to bump the revision. Historical snapshots replay with their saved
aliases; older snapshots without a profile retain the frozen compatibility defaults.
The built-in fallback is packaged Python data, independent of the working directory.
No schema change is required for this refactor; head remains `20260920_18`.

That parser-profile checkpoint did not implement the richer private applicant draft, approximate-year
tolerance, recency, transferable experience, licenses, or other new requirement
types. New fact types still require shared engine support and tests; new vocabulary
and text conventions for the existing types can be passed in as data.

## Rich evidence and cross-career validation — September 21

Applicant `experience_evidence` now also accepts schema 2 through the existing
repository and applicant CLI. `data/accounting_applicant_sample.json` is a clearly
fictional, importable example. Evaluations read the saved database record, not a
particular applicant's file or a career-specific code path. Each applicant retains
one shared policy and multiple strategies. Schema 1 evidence remains compatible.

Schema 2 separates reported approximate commercial duration, evidence state,
commercial/project context, depth, recency, expertise, aliases, explicit transfer
targets, and source statements. Unknown is different from explicitly absent.
Approximate duration shortfalls produce `gap`, not automatic rejection; explicit
transfer targets produce `adjacent`, not proof of the exact qualification. Both
remain internally held. Depth and recency are preserved for explanation but are
not yet used as requirement comparators. Expertise is never inferred from years.
The current comparison policy only supports holding numeric gaps and transferable
evidence; it does not impose an invented tolerance cutoff. Licenses and education
still need typed comparison support; background text alone cannot satisfy them.

Parser-profile schema 2 adds configurable `capability_signals` containing `name`,
`skill`, and `title_pattern`. See `data/requirement_parser_cross_career.json`.
Signals compare title spans to recorded professional evidence and describe **role
relevance only**. They neither prove eligibility nor override a mismatch. This
configuration is deliberately narrow and can miss other titles; it is not a
complete occupation classifier. Profiles, evidence, source descriptions, policy,
rule version, and facts are retained in evaluation snapshots.

The report command reads two or more database-backed applicants and records
separate relevance, qualification, queue, and tier results. It has no network calls,
but migrates and writes evaluations to its explicitly selected database. Use an
offline copy and an ignored private output path:

```powershell
.\.venv\Scripts\python.exe -m jobsearch.scripts.cross_career_report --database-url sqlite:///./data/private/cross-career-trial.db --applicant-id 1 --applicant-id 2 --parser-profile data/requirement_parser_cross_career.json --as-of 2026-09-21T12:00:00Z --output data/private/new-comparison.json
```

Optional `--expectations` accepts a JSON object with `cases`, each containing
`applicant_id`, `job_id`, `expected` record fields, and `reason`. A failing case
rolls back the evaluation batch. Existing report paths are never overwritten.
Keep applicant-specific expectations and reports private.

Verification includes database round trips, numeric gaps, unknown/absent evidence,
explicit transfers, AND/OR alternatives, two-career fixtures, snapshot replay,
evidence revisions, parser validation, and regression tests. An offline real-data
trial used 116 existing software/IT listings plus 25 newly fetched accounting
listings, with both applicant profiles persisted in the trial database. All 282
historical evaluations replayed exactly. The title/evidence signals separated the
two careers, but **no fully qualified prospective matches were established**.
Federal qualification prose, shared eligibility, and availability remain blockers.
The existing IT sample is broad IT, not a curated software-only test set, and
contains no established positive core-stack acceptance example.

The accounting collection used one successful request through the existing live
USAJOBS budget, capped at one page of 25. It uses accounting series 0510 as defined
by [OPM](https://www.opm.gov/policy-data-oversight/classification-qualifications/general-schedule-qualification-standards/0500/accounting-series-0510/)
and the [USAJOBS search API](https://developer.usajobs.gov/api-reference/get-api-search).
Its collector is disabled after the trial. The run is intentionally partial;
it does not represent the full accounting inventory. The live database retains
one applicant and no evaluations; rich profiles and trial evaluations are in the
private offline database. Do not collect through that copy's stale request budgets.
No AI scoring, worker, application automation, deployment, commit, or push was run.

## Qualification section extraction — September 21

`data/requirement_parser_federal.json` is an opt-in schema-3 profile. It adds
`qualification_sections` to schema 2: an `ats_type`, source-normalized `headings`,
an `include` list, and named clause definitions (`name`, `kind`, `pattern`).
Clause patterns use named regex captures; vocabulary stays in configuration.
Select it with the existing evaluator/report `--parser-profile` option.

`qualification-v3` extraction retains Qualifications, Requirements, and Education
sections independently. `qualification-sections-v1` captures experience durations,
grade references, degrees, graduate education duration, semester credits,
credential mentions, alternative markers, combination paths, substitution
restrictions, and external references. All captures retain original source offsets;
unparsed spans remain available. Summary and Duties are outside this extraction.
External references are recorded, not fetched or treated as satisfied conditions.

This is **clause extraction, not resolved qualification logic**. A credential mention
may belong to an optional alternative; a grade reference may describe required
prior experience rather than the advertised grade. OR markers include ordinary
prose alternatives and are not yet assembled into logical branches. Captures have
`scope_status=unresolved`; complete coverage is never asserted by this pass.
For matching sources, unresolved sections prevent the older Requirements-only
grammar from declaring qualification or rejecting an applicant on an isolated
clause. Explicit applicant exclusions and independent shared-constraint rejections
still apply. Other sources and older parser profiles retain their behavior.

The existing software/IT and accounting data were evaluated in a separate ignored
database copy using both saved applicants. All 125 federal listings yielded
qualification sections. Observations included 105 specialized-experience duration
phrases, 64 credit-hour phrases, and 46 credential mentions. These counts describe
extraction, not accuracy or satisfied qualifications. All 564 old/new snapshots
replayed exactly; no prospective matches were newly established.

The full suite passed 405 tests, including nine new section extraction tests.
Next work is explicit branch/grade scope and typed applicant education/credential
comparison. No migration, collection, or live database update was needed.

## Qualification paths and typed evidence — September 21

`data/requirement_parser_federal_paths.json` is an opt-in schema-4 profile. It
retains section extraction and adds configured basic/grade boundaries, explicit
alternative separators, and whole-branch leaf rules. A basic degree alternative
and specialized experience at a particular grade remain distinct components.
Incidental references to lower grades do not create advertised-grade branches.
Unknown alternatives remain in the tree; evidence from different grades is never
combined. Every node retains its exact source span. The grammar deliberately
recognizes only a small set of explicit heading/alternative conventions.

Evidence schema 3 adds a required `qualifications` list to schema 2. The existing
database repository and applicant CLI validate and persist it. See the fictional
`data/accounting_qualifications_sample.json`:

- Degree facts specify `level`, `field`, nullable `attained`, and `source`.
- Credential facts specify `name`, nullable `attained`, `current`,
  `by_examination`, and `source`.
- Credit facts specify `field`, nullable exact `semester_hours`, and `source`.

Missing facts remain unknown. Degree facts do not imply course credits; background
text does not establish typed facts. Current credential status and examination
basis are checked only when required. Degree alternatives list their accepted
levels explicitly; the engine does not infer a degree hierarchy. Duplicate facts
are rejected rather than summed. Source assertions are not independently verified.
Schemas 1 and 2 remain compatible, with typed facts unknown when absent.

The path configuration supplies `sections`, `basic_start`, `basic_end`,
`grade_heading` (one named `grade` capture), `branch_separator`, `wrapper`,
`local_or`, and `leaf_rules`. Each leaf rule has a full-match pattern and typed
`requirement` template; `$capture` references named captures. Templates support
`degree`, `credential`, and `credits`. Career vocabulary is configuration data.
Negated, conditional, partially recognized, or conflicting whole branches stay
unresolved. No arbitrary prose OR is automatically converted to a branch.

For example, select `--parser-profile data/requirement_parser_federal_paths.json`
with the existing evaluation/report commands. Snapshots contain the full profile,
`qualification-v4` extraction and `qualification-paths-v1` trees, typed evidence,
and local component comparisons. Report `qualification_paths` and
`*_requirement_components` counters describe local requirements, **not full-job
qualification or prospective matches**. Basic and grade components are not yet
assembled into an overall eligibility proof across all source sections.

Offline verification against the 141 stored jobs found four explicit basic blocks
and nine explicit grade blocks. Two basic degree components were supported for
the database-backed synthetic accountant; the remaining components stayed unknown.
No prospective matches were established. All 846 historical evaluations replayed
exactly. Full suite: **421 passed** (16 new tests); focused paths/sections/rich
evidence suite: **41 passed**. No schema migration or live database change was
needed. Next work is specialized-experience evidence and broader scope coverage;
foreign education, accreditation, equivalent combinations, and overall shared
eligibility remain unresolved.

## Specialized experience and work evidence — September 22

The opt-in `data/requirement_parser_specialized.json` extends the schema-4 path
profile with two whole-branch specialized-experience patterns. They cover two
accounting duty formulations seen in the stored data. Each template supplies
stable activity IDs, required months, and a grade system; the required prior
grade is captured from the source. The advertised grade stays separate. The
engine contains no accounting-specific duty names or grade hierarchy.

Applicant evidence schema 4 extends schema 3 with `work_examples`. Each example
requires `id`, `activities`, nullable `months`, `grade_equivalences`, and `source`.
Every grade equivalence requires its own `system`, `grade`, and `source` assertion.
`months` means relevant duration performing the listed activities together, not
total career tenure or the length of an unrelated job. The public
`data/accounting_work_sample.json` is explicitly fictional test evidence.
The existing applicant repository and CLI persist this evidence; no migration is
needed. Earlier evidence schemas retain their behavior and have unknown work proof.

Specialized-experience comparison requires the duty set, relevant duration, and
explicit grade equivalence in one example. Missing activities, missing duration,
or missing equivalence stay unknown. A known duration shortfall is a `gap`, not
an automatic rejection. Examples are not combined, their months are not summed,
and a numerically higher grade does not imply equivalence. These constraints avoid
double-counting or manufacturing a qualifying work history, but can hold legitimate
experience spread across several assignments. Evidence remains source-backed
assertions, not an independent verification or an agency determination.

Use `--parser-profile data/requirement_parser_specialized.json` with the existing
evaluator or report command against an offline database. Full source spans,
templates, applicant examples, duty/duration/grade checks, and unknown alternatives
are retained in snapshots. Partial, negated, conditional, or additional unrecognized
branch text remains unresolved. The grammar is intentionally narrow; it is not
general semantic matching of experience descriptions.

Verification: **441 tests passed**, including 20 new specialized-experience tests;
the focused specialized/path suite passed 36 tests. On the 141 stored jobs, the
synthetic accountant gained one supported GS-09 local experience route, while
GS-11 remained unknown. All 1,128 old/new evaluations replayed exactly in the
offline copy. No full-job prospective match was established. Overall requirement
composition, broader duty coverage, and shared eligibility still need work.
No live database update, API call, worker, deployment, commit, or push occurred.

## Overall qualification composition — September 22

`data/requirement_parser_composed.json` opts into parser schema 5. It adds a
`qualification_composition` configuration with a target `section` and a full-match
`bridge` pattern connecting the basic requirement to the grade requirements.
`qualification-v5` extraction snapshots `qualification-composition-v1` output.
Earlier parser profiles retain component-only behavior.

Where the source scope is explicit, the composed rule is **basic requirements
AND any one grade route**. Per-grade results include the same shared basic
requirement; a supported grade cannot rescue a failed basic requirement. Unknown
alternatives remain viable, and unrelated sections or duplicate grades are never
merged. The parser currently requires one basic block and unique grade headings
in one configured section, linked by the recognized bridge.

Remaining leading text and other configured qualification sections are retained
as uncovered evidence. They prevent both qualification approval and a composed
rejection, since they may contain exceptions or additional conditions. Complete
structural coverage still requires applicant evidence to support the composed
tree. Coverage is limited to the configured normalized qualification sections;
this is not a general understanding of every statement in an announcement.

Reports now include `overall_qualification` (coverage, blockers, and combined
per-grade statuses) separately from `readiness_blockers` (unresolved/rejecting
shared checks such as availability, geography, and eligibility). A supported
qualification assessment cannot clear those checks or authorize an application.

Full suite: **455 passed**; focused composition/specialized suite: **34 passed**.
The real-data trial composed routes for two listings. For the synthetic accountant,
job 117's basic requirement AND GS-09 route were supported together, but uncovered
source conditions and shared readiness checks kept the overall result unresolved.
All 1,410 saved evaluations replayed exactly in the offline copy. No live changes,
new collection, migration, worker, deployment, commit, or push were performed.
Next is resolving the specific uncovered conditions and shared eligibility facts;
broader source conventions and grade structures still need coverage.

## Source conditions and eligibility separation — September 22

The opt-in schema-6 profile `data/requirement_parser_conditions.json` adds
`qualification_conditions`: whole-block patterns for explicitly recognized source
guidance and foreign-education conditions. Vocabulary, accepted citizenship
spellings, country codes, and application obligations are supplied as data. The
current profile recognizes two specific source boilerplate forms; changed or
additional wording stays unresolved. Matching text is retained as evidence rather
than discarded. `qualification-v6` and `qualification-conditions-v1` are snapshotted.

Degree and credit facts may now include nullable `education_country`, nullable
`recognized_in` (country-code list), and nullable `transcript_available`.
Country codes are uppercase two-letter identifiers. These fields are optional for
existing evidence and require explicit source assertions when supplied; applicant
location, nationality, degree names, and career history do not fill them in.
`data/accounting_conditions_sample.json` is fictional evidence with an explicit
US education-country assertion. No real applicant evidence was enriched.

A recognized foreign-education condition follows the degree or credit branch
used to qualify. A domestic education assertion or explicit recognition in the
required country can support that branch. Missing origin/recognition remains
unknown. Facts from different credentials cannot be combined to manufacture
support, and a qualifying non-education alternative does not require degree
provenance. These are applicant assertions, not independent credential verification.

Source citizenship conditions compare against positive citizenship assertions
already stored in the shared search policy. Empty lists and other citizenships
do not establish that the applicant lacks the required citizenship. A new separate
`citizenship` check reports support or review; all other hiring eligibility checks
remain independent. Resume evidence and conditional transcript requirements are
reported under `source_conditions` as application-preparation obligations, not
qualification failures. Actual possession/submission of documents is not inferred;
`transcript_available` is retained but does not automatically complete those tasks.

Full suite: **478 passed**, including 23 new condition/evidence tests. The real-data
trial used a new offline copy and updated only the fictional applicant's education
country and citizenship assertions. Job 117's parsed qualification tree and
citizenship condition were supported for that applicant. The full job still stayed
held: availability, work arrangement, geography, employment, policy exclusions,
and other eligibility checks remain unresolved. One qualification pass does not
establish broad parser accuracy or independent employer eligibility.

All **1,692 historical evaluations** replayed exactly. The live database remained
unchanged, and no migration, network request, worker, deployment, commit, or push
was performed. Next work is structured shared-job facts and explicit resolution
of the remaining shared constraints, without treating missing data as a pass.

### Software-profile baseline validation — September 23, 2026

An offline validation using the unchanged database-backed software applicant
exposed a substantial extraction gap. Ten manually inspected real listings had
expectations frozen before evaluation: all ten routed as expected, but only one
passed the minimum required-concept extraction check. Correctly holding a job
does not demonstrate that its requirements were understood. The known stack
mismatch still rejected when the manual exclusion was removed in memory.

Across 141 stored jobs, 36 were do-not-pursue and 105 unresolved; none received a
tier. Qualification was unknown for 140 and mismatched for one. Four synthetic
comparison controls passed, but are not evidence of real positive matches.
The stored sample lacks a verified core-stack positive vacancy; matching terms
in advertisements for other openings were excluded from that assessment.

Validation replayed 1,739 historical evaluations exactly and passed database
integrity checks. The focused regression suite passed 79 tests; the earlier
478-test full-suite result was not rerun. Private expectations and reports remain
Git-ignored. No production parser changes or live database writes occurred.
The next priority is ordinary software requirement sentences/headings and
correct separation of multiple advertised roles, before expanding readiness
checks. Extraction failures must remain distinct from missing applicant evidence.

### Scope decision - September 24, 2026

Broader career and federal-parser expansion is paused. The active milestone is a
useful local software-job pilot with real positive candidates and a checked
shortlist. [ROADMAP.md](ROADMAP.md) records next steps, completion criteria and
resume notes. This supersedes earlier next-step suggestions; safety checks remain.

September 24 checkpoint: full suite rerun, **478 passed**. Step 1 has an ignored
frozen acceptance artifact containing ten real source snapshots and expectations:
eight software development cases and two deferred federal regressions. None is an
unseen validation case. Saved backups/cache supplied no additional job identities.
Real positive candidates and a separately reserved validation subset are still
needed; the acceptance set is explicitly incomplete. No parser changes or live
collection were made for this checkpoint.
