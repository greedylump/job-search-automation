from __future__ import annotations

from jobsearch.models.job import Job


class FilterRule:
    """Simple deterministic interface for filtering jobs based on a placeholder rule."""

    def __init__(self, name: str):
        self.name = name

    def should_keep(self, job: Job) -> bool:
        return True


class MinimumTitleRule(FilterRule):
    def __init__(self):
        super().__init__("minimum_title")

    def should_keep(self, job: Job) -> bool:
        return bool(job.title and len(job.title.strip()) >= 2)


class JobFilter:
    """Source validity checks, independent of applicant suitability."""

    def __init__(self, rules: list[FilterRule] | None = None):
        self.rules = [MinimumTitleRule()] if rules is None else rules

    def filter(self, jobs: list[Job]) -> list[Job]:
        kept: list[Job] = []
        for job in jobs:
            if all(rule.should_keep(job) for rule in self.rules):
                kept.append(job)
        return kept
