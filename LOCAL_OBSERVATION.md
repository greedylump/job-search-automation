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

## Facts and availability checkpoint — September 20, 2026

Full regression suite: **334 passed**, including 46 facts/availability tests.
Checks cover date boundaries, ambiguous/negated requirements, retained source
evidence, old-rule replay, state-sensitive history, and read-only CLI behavior.

Added `job-facts-v1` extraction and a read-only SQLite inspection CLI. Facts are
applicant-independent and carry exact source text/offsets. New `tier-policy-v2`
evaluations snapshot those facts and assessment time; old v1 replay is retained.
No schema change was required. Canonical employment aliases do not overwrite
source labels, and deadline outcomes do not overwrite shared job status.

At the fixed assessment time `2026-09-20T12:00:00Z`, the 116 stored records yielded
87 before their reported deadline, 6 deadline-uncertain, 7 past, and 16 unknown.
The timezone guard intentionally leaves some calendar-past dates unresolved.
Four records contain narrowly recognized mandatory clearance evidence. Canonical
employment values are 10 full-time, 1 part-time, 3 contract, and 102 unknown.

Temporary-copy evaluation: 8 distinct rejects, 108 review, no keeps. Reject reasons
include 7 availability failures and 4 clearance conflicts, with overlap. All 116
results replayed and were reused on repeat assessment within the same deadline
state. Schema comparison, SQLite integrity, and foreign-key checks passed. The
verification copy was removed. Live counts remain 116 jobs, 7 runs, 4 attempts,
and zero evaluations; the live file was opened read-only.

Requirements extraction is deliberately limited to affirmative Secret/Top Secret
sentences in the normalized USAJOBS Requirements section. Conditional, negated,
potentially waived, and unrecognized statements remain for review. Dates do not
verify actual employer availability or extensions. Existing ingestion does not
refresh descriptions/deadlines on duplicate jobs. Broader facts, source refresh,
role aliases, and separation of review priority from eligibility remain next work.
No AI, network collection, worker, deployment, commit, or push was performed.

## Qualification gate checkpoint — September 20, 2026

Full suite: **361 passed**, including 27 new qualification-gate tests. Tests cover
known mismatches versus missing evidence, both OR branches, no branch mixing,
ambiguous/negated requirements, evidence edits and replay, and prospective-output
suppression for held jobs. `git diff --check` passed.

Added explicit commercial-experience bounds, expertise evidence, and source-keyed
applicant job exclusions, with validated applicant CLI updates. New evaluation
snapshots include the evidence and versioned AND/OR requirement structure. Queue
states distinguish `do_not_pursue`, `unresolved`, and `plausible`. Held jobs are not
applicant review requests and do not receive assigned tiers. Evaluation output hides
held/excluded details unless `--show-all` is supplied; history remains inspectable.

A temporary copy migrated from `20260918_17` to `20260920_18`. With the existing
profile, 8 results were do-not-pursue and 108 unresolved at the fixed assessment
time `2026-09-20T12:00:00Z`. Applying the user's explicit job exclusion to the copy
produced 9 do-not-pursue and 107 unresolved, with no assigned tiers. This did not
invent any commercial experience durations. The actual requirement example parsed
its commercial OR branches and expertise requirements, with remaining coverage
explicitly incomplete. No automatic prospective opportunities are claimed.

Replay, repeat-evaluation idempotency, schema comparison, integrity, and foreign-key
checks passed on the copy. It was removed. The private evidence update was prepared
under `data/private/` but not imported into the live database. Live counts remain
116 jobs, 7 runs, 4 attempts, zero evaluations, and migration `20260918_17`.

Shared geography/eligibility checks remain unresolved, and the extraction grammar
is narrow. Those limitations prevent automatic promotion until additional evidence
and checks exist. Existing facts/availability work was preserved. No live collection,
worker, AI call, deployment, commit, push, or live-data modification occurred.

## Parser-profile separation — September 21, 2026

Full suite: **374 passed**; focused parser/qualification tests: **40 passed**.
The 13 new tests include accounting/nursing vocabulary, AND/OR comparison,
unknown evidence, malformed profiles, and snapshot isolation after profile edits.

Requirement extraction now accepts validated profiles for vocabulary and text
conventions. Shared AND/OR comparison and conservative coverage logic remain common
across careers. Software and accounting JSON examples are public fictional
configuration; accounting/nursing tests exercise different applicant evidence.
Full profile definitions are snapshotted for fingerprinting and historical replay.
No live database migration, evaluation, collection, or private profile import was
performed. Prior uncommitted facts, availability, and qualification work is preserved.

## Database-backed rich evidence and accounting trial — September 21, 2026

Full suite: **396 passed**. The new evidence/cross-career coverage adds 22 tests
relative to the 374-test parser checkpoint. A Windows sandbox restriction on the
pytest temporary directory required rerunning the focused tests with permission;
the six focused cross-career tests then passed.

Evidence schema 2 is career-neutral and consumed from the applicant database row.
It preserves reported approximation, unknowns, explicit absence, commercial/project
context, depth, recency, expertise, and explicit transfer targets. Numeric gaps
and transferability hold without automatic rejection. It does not infer expertise
or implement numeric tolerance thresholds, credential checking, or recency rules.
Parser schema 2 adds configurable title-to-capability signals, explicitly separate
from mandatory qualification and prospective-queue admission.

The ignored `data/private/cross-career-trial.db` contains two persisted profiles:
the private software profile and the clearly fictional accounting sample. Each has
its own shared policy and tier strategies. Four predeclared checks against existing
jobs passed: explicit exclusion, missing evidence held, known rejection retained,
and no unsupported cross-career relevance. These expectations and detailed results
are private. There is no established real positive core-stack example in this
sample; synthetic supported comparisons do not establish real-world precision.

Live collection ran only after offline migration/evaluation checks and a SQLite
backup to `data/backups/before-accounting-trial-20260921.db`. Live head is now
`20260920_18`. A new `usajobs-accounting-trial` collector used the existing shared
USAJOBS budget, accounting series 0510, page size 25, and a one-page cap. One HTTP
200 returned 25 records: 25 inserted, zero invalid, zero duplicate. Run status is
`partial` because of the deliberate cap. The collector was disabled in `finally`.
No independent copied budget was used for HTTP.

Live counts: **141 jobs, 8 processing runs, 5 request attempts, 1 applicant, 0
evaluations**. Existing applicant evidence was not replaced in the live database.
The 25 collected jobs were copied to the offline trial, which now holds 141 jobs,
two applicants, and 282 evaluations. Ingestion metrics were not modified by the
offline evaluations. Live and trial integrity checks returned `ok`, with no
foreign-key violations. All 282 saved evaluations replayed exactly, and repeat
evaluation of the original 116 jobs reused the existing snapshots per applicant.

The real-data comparison showed career separation at the role-relevance layer;
neither profile received a prospective match or assigned tier. All 25 accounting
descriptions still have unresolved qualification coverage. A title signal is not
an invitation to apply or a human review request. Remaining priorities are broader
source-specific qualification extraction (including federal alternatives), typed
education/license evidence, resolvable geography/eligibility/availability checks,
and a real positive acceptance case. Shared dimensions remain separate; no AI,
worker, deployment, commit, push, or application automation was performed.

## Qualification parsing first pass — September 21, 2026

Added configurable parser-profile schema 3 and the federal section profile.
Source-normalized Qualifications, Requirements, and Education are extracted
separately, with exact source spans, named clause captures, and retained unparsed
text. Clause types include specialized-experience duration, grades, degree/credit
references, credentials, combinations, alternatives, and substitution restrictions.
These are observations with unresolved scope, not mandatory requirement leaves.

Focused parser/section/cross-career suite: **28 passed**. Full suite: **405 passed**.
New tests cover source/section boundaries, exact offsets, alternatives spanning
sections, unparsed/external references, reusable nursing vocabulary, profile
snapshot isolation, malformed patterns, and grade/substitution mentions. An
isolated Requirements mismatch is held when federal qualification alternatives
remain unresolved. Existing profiles retain their prior behavior.

Offline verification used `data/private/qualification-parsing-trial.db`, a new
copy of the earlier two-applicant trial. The sandbox blocked creating this file;
the same verification was rerun with permission. All four existing acceptance
cases passed. All 125 federal jobs had qualification sections: 105 specialized
experience duration observations, 64 credit-hour observations, and 46 credential
mentions. Alternative-marker counts include ordinary prose ORs; no branch accuracy
or complete qualification coverage is claimed. The detailed private report is
`data/private/qualification-parsing-validation.json`.

The copy holds 564 historical evaluations, all replayed exactly. Integrity was
`ok` and foreign-key checks were empty. The live database remains at 141 jobs,
8 runs, 5 attempts, and zero evaluations. No new migration or network request was
performed. Existing uncommitted changes and private profiles were preserved.
Next: resolve explicit grade/alternative scope, then compare typed education and
credential evidence. This pass intentionally does not promote held jobs.

## Qualification paths and typed facts — September 21, 2026

Full suite: **421 passed**. Focused paths/sections/rich evidence suite: **41
passed**. Sixteen new tests cover basic versus grade requirements, explicit OR
alternatives, no mixing across grades, incidental grade references, negation and
conditional prose, missing versus absent facts, credential examination/current
status, exact credit counts, cross-career reuse, malformed configuration, database
round trips, evidence revisions, and historical replay.

Parser schema 4 is opt-in through `data/requirement_parser_federal_paths.json`;
earlier profiles keep their behavior. Evidence schema 3 adds typed degree,
credential, and semester-credit assertions without a database migration. The
fictional `data/accounting_qualifications_sample.json` records its existing degree
and CPA claims explicitly, leaving credential currency and examination basis
unknown. No real applicant degree, credit, or license facts were invented.

Offline verification used a fresh `data/private/qualification-paths-trial.db`
copy. The sandbox denied database creation; the same operation succeeded with
permission. Only the synthetic applicant's evidence was updated in that copy.
The report is `data/private/qualification-paths-validation.json`.

Across 125 federal listings, the narrow scope grammar found four basic and nine
grade components. The synthetic accountant supported two basic degree components;
all nine grade components remained unknown. A predeclared check confirmed the
direct degree alternative in real job 117, while the full job stayed unresolved.
All four prior software acceptance cases passed. These are local component
results, not validated overall qualification. Unsupported branches and source
sections remain in the snapshots and prevent automatic promotion.

All **846 old/new evaluations** replayed exactly. Copy integrity returned `ok`
and foreign-key checks were empty. Live counts stayed at **141 jobs, 8 runs,
5 attempts, zero evaluations**. No migration, HTTP request, worker, deployment,
commit, or push occurred; prior work and private inputs were preserved.
Next: specialized-experience proof and broader explicit scope, then the remaining
education equivalencies and shared eligibility checks. A matching basic degree
cannot establish the specialized experience required for a grade.

## Specialized-experience comparison — September 22, 2026

Full suite: **441 passed**. Focused specialized/path suite: **36 passed**.
Twenty new tests cover source spans, advertised versus prior grade, relevant
duration, gaps, missing equivalence, general skills versus work evidence, no
combining examples or summing durations, alternative/grade isolation, conditional
and partial text, software vocabulary through the same engine, malformed evidence,
database round trips, evidence revisions, idempotency, and snapshot replay.

Added evidence schema 4 with sourced work examples and explicit grade-equivalence
assertions. Added two whole-branch specialized-experience rules through the
opt-in `data/requirement_parser_specialized.json`; duty IDs and wording stay in
configuration. The synthetic sample is `data/accounting_work_sample.json`.
No real applicant work history, duties, duration, or grade equivalence was invented.

Verification used a fresh ignored `data/private/specialized-experience-trial.db`
copy. Windows sandbox restrictions blocked creation; rerunning the same script
with permission succeeded. Only the synthetic applicant's evidence was updated
in this copy. The private result is
`data/private/specialized-experience-validation.json`. Assessment time remains
fixed at `2026-09-21T12:00:00Z` to isolate parser/evidence changes from time passage.

Across 141 jobs, the synthetic accountant supported two basic components and
one grade component; eight grade components stayed unknown. The real job 117
acceptance check confirmed the GS-09 work route, with GS-11 still unknown. The
other profile's missing work examples remained unknown. All four prior software
acceptance checks passed. Both applicants still have 11 do-not-pursue and 130
unresolved results, with no prospective matches or assigned tiers. These are
local component comparisons, not proof of overall eligibility.

All **1,128 historical evaluations** replayed exactly. Offline integrity was `ok`
and foreign-key checks were empty. Live counts remained **141 jobs, 8 processing
runs, 5 attempts, zero evaluations**. Prior uncommitted work and private inputs
were preserved. No migration, network collection, worker, deployment, commit, or
push occurred. Next priorities are composition of basic and grade requirements,
broader supported duty patterns, and the remaining shared eligibility checks.

## Overall qualification composition — September 22, 2026

Full suite: **455 passed**. Focused composition/specialized suite: **34 passed**.
Fourteen new tests cover shared basic requirements AND alternative grades,
mandatory basic mismatch, unresolved grade alternatives, extra leading/education/
requirement conditions, exact uncovered spans, missing/repeated/reversed scope,
bridge validation, nested basic alternatives, shared eligibility/availability
blocking, and compatibility with the older component-only profile.

The opt-in schema-5 profile is `data/requirement_parser_composed.json`. It requires
an explicit basic-to-grade connector and composes only one basic block with unique
grades in the same section. It records remaining source conditions as blockers;
local support does not silently become full qualification. Reports expose overall
qualification separately from shared readiness blockers.

Offline verification copied the prior database to ignored
`data/private/composition-trial.db`, with the private report at
`data/private/composition-validation.json`. No applicant evidence was changed.
The write ran with permission because Windows sandbox restrictions had blocked
database creation in this directory. Assessment time remained fixed at
`2026-09-21T12:00:00Z` to isolate rule changes from time passage.

Two real listings had composable routes. A predeclared check confirmed that job
117's basic requirement AND GS-09 experience route were supported for the synthetic
accountant, while overall coverage and shared readiness remained blocked. The
four existing software acceptance checks passed. No prospective match or assigned
tier was produced; both applicants retain 11 do-not-pursue and 130 unresolved jobs.

All **1,410 historical evaluations** replayed exactly. Offline integrity and
foreign-key checks passed. The live database was not written; no API, migration,
worker, deployment, commit, or push occurred. Remaining work is explicit resolution
of uncovered source conditions and shared eligibility, plus broader scope coverage.

## Source conditions and citizenship — September 22, 2026

Full suite: **478 passed**. The initial focused source-condition/composition suite
passed 35 tests; two additional credit-record and configurable-country tests were
included in the final full run. Twenty-three tests were added in this checkpoint.
Coverage includes missing and foreign education provenance, explicit recognition,
no mixing across credentials, non-education alternatives, positive-only citizenship,
changed source conditions, document preparation versus qualification, malformed
metadata, ambiguous rules, database policy/evidence changes, and historical replay.

Parser schema 6 is opt-in through `data/requirement_parser_conditions.json`.
It recognizes two complete source boilerplate forms. Citizenship is assessed from
the snapshotted policy; foreign-education conditions are applied to the particular
degree/credit branches used by the composed tree. Degree/credit evidence may carry
education-country and recognition assertions. Missing values remain unknown.
Resume/transcript obligations are application preparation, separate from the
qualification result. Neither source conditions nor private applicant details were
generalized from one job into unrelated records.

Offline verification used ignored `data/private/source-conditions-trial.db` and
`data/private/source-conditions-validation.json`. Creation ran with permission
because of the previously observed Windows sandbox restriction. Only the synthetic
accountant's evidence and revision-checked policy were updated: a fictional US
education-country assertion and fictional US citizenship. Real applicant evidence
was untouched. Assessment time remained fixed at `2026-09-21T12:00:00Z`.

For real job 117, the synthetic accountant now has supported overall parsed
qualification and citizenship results. Across the 25 accounting jobs, one
qualification result is supported and 24 remain unknown for that applicant.
The job is still unresolved with no tier because other shared checks remain:
availability, work arrangement, geography, employment, policy exclusions, and
broader eligibility. Both applicants still have 11 do-not-pursue and 130 held
results overall. All four prior software acceptance checks passed.

All **1,692 old/new evaluations** replayed exactly. Offline integrity and
foreign-key checks passed. Live counts remain **141 jobs, 8 processing runs,
5 request attempts, zero evaluations**. No migration, API request, worker,
deployment, commit, or push occurred. Existing work and private inputs were kept.
Next is evidence-backed resolution of shared job facts and constraints; the
source-condition grammar and real-data validation remain deliberately narrow.

## Actual software-profile validation — September 23, 2026

Validated unchanged applicant 1 from the latest offline database, confirming its
evidence exactly matches the approved private evidence payload. Expectations for
ten manually inspected software-related listings were frozen before evaluation.
Used parser schema 6 and requested assessment time `2026-09-23T12:00:00Z` in a new
ignored `data/private/software-profile-validation-20260923.db` copy. No profile
updates or parser changes were made. Accounting applicant results were not run.

All ten selected routing expectations passed, but only **1/10 minimum concept
extraction checks passed**. The remaining nine lack required skill or grade-route
concepts in semantic requirement trees. This is a parser coverage failure even
though conservative holding prevents promotion. Concept presence alone is also
insufficient to establish complete scope or AND/OR semantics. The known stack
rejection survives removal of manual exclusions in an in-memory counterfactual.

All 141 stored jobs were assessed for the actual applicant: **36 do-not-pursue,
105 unresolved, zero tiers**. Qualification is unknown for 140 and mismatched for
one. At the later assessment time, 47 evaluations were newly stored and 94 reused
their original snapshots because fingerprinted inputs/facts were unchanged.
These queue totals include availability and other shared constraints; they are
not 36 demonstrated qualification mismatches.

Four synthetic job controls using the actual database-loaded profile passed:
supported evidence, numeric gap, explicit professional absence, and unrecorded
skill. They were never inserted as real jobs and do not fill the missing real
positive sample. Core-stack keyword mentions in the stored listings were found
in advertisements for unrelated openings rather than a verified suitable vacancy.

All **1,739 historical snapshots** replayed with identical reasons and queue state.
Offline integrity/foreign-key checks passed; job rows and applicant evidence were
unchanged. Live counts remain **141 jobs, 8 processing runs, 5 request attempts,
zero evaluations**. The offline source retains its earlier ingestion counts.
The focused evidence/gate/parser-profile/source-condition suite passed **79 tests**.
The previously recorded 478-test full suite was not rerun for this validation-only
checkpoint. Detailed expectations, script, JSON and Markdown reports are ignored
under `data/private/`. Windows sandbox blocked database creation; the approved
retry created only the offline copy and private reports.

No API requests, workers, migrations, deployment, commit, or push occurred.
Next: ordinary software requirement sentences and headings, then distinct role
and alternative scopes. Federal grade-route and production-depth semantics remain
gaps. Do not treat these parser failures as questions the applicant must answer.
## Acceptance-set checkpoint - September 24, 2026

Full suite freshly rerun: **478 passed in 132.86 seconds**, including temporary
database migration coverage. Git diff whitespace check passed. Existing evaluation
work forms a checkpoint with the scope freeze; no parser behavior changed today.

Step 1 created ignored `data/private/software-pilot-acceptance-v1.json` via the
private `freeze-software-pilot.py` script. It freezes ten actual source rows,
source hashes, approved database-backed evidence and hash, expected qualification,
queue/tier outcomes, quoted evidence and required scope semantics. Eight cases
are software pilot development cases; two federal cases are deferred regressions.
Previously inspected cases are explicitly not called an unseen validation set.
The historical assessment clock stays September 23; fresh availability must be
checked separately before any prospective shortlist.

Read-only inventory of all six saved backups and the 16-job Remotive cache found
no job identities beyond the current 141 stored jobs. Public job fixtures are
synthetic and cannot supply genuine positive cases. Three real-positive slots and
three unseen-validation slots remain unfilled; these are sampling targets, not
evidence or guarantees of fit. No external collection was attempted. The artifact
is deliberately partial, and expectations must not be edited to match parser
output. Windows sandbox blocked the private JSON write; an approved retry created
it. No live database changes, worker, deployment, or API calls occurred.

## Scope freeze - September 24, 2026

The user paused broader scope for a useful local software-job pilot.
[ROADMAP.md](ROADMAP.md) records the sequence, completion criteria and resume
notes for cross-career work, federal grammar, broader eligibility, AI and deployment.
Existing implementation and uncommitted work are preserved. Next is a real
software acceptance set including genuine positive candidates, followed by common
requirement parsing and a checked local shortlist. No new live collection is
authorized by this decision. Documentation only; no tests rerun or database writes.
