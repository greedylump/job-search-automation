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


class RemoteOnlyFilterRule(FilterRule):
    def __init__(self):
        super().__init__("remote_only")

    def should_keep(self, job: Job) -> bool:
        # Placeholder deterministic rule: remote-only accepts only a true remote signal.
        if job.remote_type:
            return job.remote_type.lower() == "remote"
        return False


class JobFilter:
    """Composite filter that applies a chosen set of rules in order."""

    def __init__(self, rules: list[FilterRule] | None = None):
        self.rules = rules or [MinimumTitleRule(), RemoteOnlyFilterRule()]

    def filter(self, jobs: list[Job]) -> list[Job]:
        kept: list[Job] = []
        for job in jobs:
            if all(rule.should_keep(job) for rule in self.rules):
                kept.append(job)
        return kept
