# Scope checkpoint: September 24, 2026

This supersedes earlier next-step suggestions in README and LOCAL_OBSERVATION.
Preserve all existing implementation, tests, and uncommitted work.

## Active milestone: useful local software-job pilot

1. Freeze a compact real-job acceptance set using the actual database-backed
   applicant: plausible matches, definite mismatches, and inconclusive cases.
   Start with the ten September 23 cases, then add genuine positive candidates.
   The current corpus lacks a verified core-stack positive. Inspect saved material
   first; new live API collection requires explicit authorization. Record source
   text, dates, expected outcomes and reasons before changing parsing. Reserve
   some cases for validation without tuning the parser against them.
2. Fix common requirement headings and experience sentences, required versus
   preferred skills, alternatives, and separate advertised roles. Keep vocabulary
   configurable and retain source evidence and parser versions. Exclude unrelated
   role advertisements. Do not attempt exhaustive deterministic language parsing.
3. Evaluate the acceptance set and stored corpus offline with the actual profile.
   Measure extraction separately from routing. Distinguish parser failures,
   missing applicant evidence, and shared-constraint blockers. Resolve shared facts
   needed for the pilot using evidence; never weaken gates to create positives.
4. Produce a readable local shortlist with reasons and gaps, rejection explanations,
   and a separate internal holding report. Parser failures are engineering tasks,
   not applicant review tasks. Tier assignment follows viability. Keep hireability,
   career value, income value, and application friction separate.
5. Verify the complete local workflow with relevant regressions, the full suite,
   fresh temporary database migrations, historical replay, and repeatable reports.
   Assess deployment separately afterward: scheduling, backups/restore, monitoring,
   recovery, and operational limits for the chosen environment.

Completion requires demonstrated real positive candidates, no known hard mismatch
promoted in the acceptance set, correct required/preferred and alternative scope
for supported forms, and explicit unsupported-coverage reporting. Report missed
positives and held cases, including reserved validation cases. Synthetic controls
and test counts alone do not establish usefulness. A small acceptance set does
not prove broad accuracy. No AI or application automation in this milestone.

## Paused work and how to resume

- Cross-career expansion and accounting collection/validation: preserve sample
  profiles, configurable parsers, cross-career reports and tests. Resume after a
  useful software pilot and user agreement to broaden scope. Freeze a two-career
  acceptance matrix using database-backed fictional accounting evidence; measure
  positives, mismatches and unknowns separately. Unknown is not automatic rejection.
- Additional federal grammar (NH/GS routes, education substitutions, specialized
  experience and source-condition variants): preserve schema 3-6 and regressions.
  Resume for an explicit target use case with representative listings and expected
  outcomes, rather than adding whole-block patterns for isolated examples.
- Broad eligibility/document workflows beyond pilot needs: existing checks stay
  enforced. Resume from concrete shortlist blockers; distinguish qualifications,
  eligibility and application preparation.
- AI, application automation and deployment remain separate future decisions.
  Do not restart them automatically after the pilot. Recorded parser failures can
  inform a later bounded AI extraction experiment.

Before resuming, reread Git status/diff, README, LOCAL_OBSERVATION and local
instructions. Inspect preserved evaluation modules, parser configurations and
tests before adding schemas or abstractions. Preserve snapshot replay behavior.
Checkpoint: migration `20260920_18`, tier rules v4, parser schema 6. Latest full
suite: 478 passed; latest focused suite: 79 passed. September 23 baseline: only
1/10 minimum extraction checks passed despite 10/10 expected routing outcomes.

Private resume artifacts remain Git-ignored under `data/private/`: September 23
software expectations, validation script/report/database, approved evidence, and
the preceding source-conditions trial. Keep applicant details out of public
fixtures/docs. Evaluation reads database evidence; private JSON is an input
artifact, not a hardcoded runtime dependency.
