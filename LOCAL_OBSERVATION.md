# Local collection observation — September 17, 2026

The first authenticated USAJOBS sample contained 100 new jobs; Remotive returned
15 duplicates. The SQLite file grew 774,144 bytes to 974,848 bytes. These are one-run
measurements, not a sustained growth forecast. Both providers remain subject to
their recorded budgets and six-hour refresh deadlines.

## Coverage and relevance

USAJOBS uses public IT series 2210 without a location constraint. The expanded
configuration permits three 100-result pages per refresh, up from one. Page caps
still produce partial runs; this is not a complete inventory or historical backfill.
Mutable page-number searches restart from page one on the next refresh and deduplicate.

Read-only review of the initial 100 USAJOBS titles found the following overlapping
keyword groups (not applicant-fit scores):

| Title group | Jobs |
| --- | ---: |
| Software, applications, developer, programmer | 7 |
| Security, INFOSEC, cyber | 41 |
| Supervisor, chief, director, manager | 25 |
| SYSADMIN, network, support, CUSTSPT | 24 |

All 100 have a recognized salary period, but currency and remote-work status are
unknown in the current normalized sample. Telework is not treated as remote.
Thirteen locations contain negotiable/multiple/various wording. Numeric salary
alone cannot support a currency-sensitive comparison. Federal hiring eligibility
also requires review beyond the source's public-search setting.

At the initial observation, there was no applicant profile in the live database.
Target roles, geographic and remote constraints, salary floor, and federal
eligibility had been requested. The September 18 checkpoint below supersedes that
profile status.
No personal preferences were invented, and no jobs were rejected on that basis.
If software development is the target, IT-series coverage needs closer review:
title-only developer matching would miss federal titles such as IT Specialist
(Applications Software). Broad ingestion remains in place while tier-aware
evaluation is pending.

## Observation

Use the bounded local worker and `observation_report` commands in README. Actual
multi-cycle evidence requires the next scheduled refreshes; offline clock-controlled
tests do not substitute for live yield measurements. New jobs, duplicates, partial
coverage, HTTP failures, disk growth, and pauses remain visible in the database and
rotated worker logs. Retention is opt-in, dry run by default, and preserves aggregate
history before deleting eligible old run/request records. The live database is too
new for the default 180/365-day retention periods to remove any history.

## Expansion and retention checkpoint

The live USAJOBS row now allows three pages of 100 records; its next-due time was
preserved at September 18, 03:43 UTC (September 17, 10:43 PM Central). Remotive's
deadline was also unchanged. No additional live requests were made during this
change. A verified SQLite backup preceded migration to `20260917_16`.

Full regression suite: **256 passed**, followed by **6 retention tests passed**
after adding the populated-aggregate downgrade safeguard. Tests cover dry-run
non-mutation, atomic rollback, repeated cleanup, null metrics, independent request
and run retention, active quota windows, unfinished records, future deadlines,
and rejection of budget windows spanning pruned detail. A real one-second bounded
worker loop exited automatically without a request during the cooldown.

Live retention dry run: zero eligible requests and zero eligible runs; no live
history was deleted. Storage accounting reported approximately 2.86 MB including
local backups, with about 115 GB free on the development filesystem.

The proposed 18-hour-20-minute background launch was declined. **No background
observation worker was started.** Multiple live refresh cycles are still pending;
run the bounded foreground command in README when ready. Applicant-specific
filter changes remain pending tier-policy evaluation implementation.

## Applicant policy checkpoint — September 18, 2026

The supplied preferences are now saved privately as one applicant, one shared
search policy at revision 1, and four enabled A–D strategies. Private input files
and database backups are Git-ignored; no personal policy values are published here.
A verified backup preceded migration to `20260918_17`. Database integrity and
foreign-key checks passed, and saved definitions match the private import bundle.

Full test suite: **265 passed**. Live counts remain 116 jobs, 7 processing runs,
and 4 request attempts. No new collection requests or evaluations were performed.
At that checkpoint, tier assignment and policy-aware evaluation were pending;
the legacy evaluator refused applicants with a saved tier policy.

## Tier evaluation checkpoint — September 18, 2026

`tier-policy-v1` now evaluates the shared constraints and routes configured title
phrases to enabled A–D strategies for one applicant. All matching strategies are
recorded; A–D precedence selects provisional tailoring guidance. Unmatched titles
remain unassigned for review. Known arrangement/employment conflicts can reject;
unknown eligibility, geography, clearance, physical demands, credentials, value,
and application effort remain explicit review items. There is no automatic keep
decision in this first policy evaluator. The four value dimensions stay separate
and unscored. No AI or application automation is included.

Policy revisions, complete strategy definitions, relevant profile/job inputs, and
rule versions are saved with each distinct evaluation. Repeated inputs reuse the
existing result; changed inputs create history. The schema remains `20260918_17`.
Retention changes remain intact, and evaluations do not modify collection metrics
or shared job records.

Verification: **93 focused tests passed**, then **288 full-suite tests passed**.
Coverage includes legacy behavior, overlap/disabled strategies, unknown facts,
policy/profile/job/rule changes, snapshot replay, and atomic CLI rollback. Migration
tests use temporary databases, including schema comparison and historical rows.

A temporary SQLite backup of the locally configured database produced 116 review
results, all unassigned because no configured whole title phrase matched. All 116
results replayed identically from snapshots and were reused on a second evaluation.
Schema comparison, integrity, and foreign-key checks passed. This is not evidence
of successful routing coverage or applicant suitability. Geographic interpretation,
role aliases, requirement extraction, and evidence-based value/effort assessment
remain limitations. Broader matches should be introduced with explicit rules and
tests, without inventing experience or treating missing evidence as eligibility.

The live database was read-only throughout verification and still has 116 jobs,
7 processing runs, 4 request attempts, and zero evaluations. Temporary-copy cleanup
initially encountered a Windows file lock; the exact leftover verification files
were removed after the process exited. No worker, live API request, deployment,
commit, push, or live-data deletion occurred.
