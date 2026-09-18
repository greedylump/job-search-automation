from datetime import timedelta

from sqlalchemy import select, text

from jobsearch.models import RequestAttempt, RequestBudget, RequestBudgetWindow, DailyMetric
from jobsearch.storage.database import get_session, close_session


def eligible_at(session, budget, now):
    """Compute all rolling-window deadlines under the caller's reservation lock."""
    deadlines = [budget.next_allowed_at] if budget.next_allowed_at else []
    rules = session.scalars(select(RequestBudgetWindow).where(RequestBudgetWindow.budget_name == budget.name))
    for rule in rules:
        recent = list(session.scalars(select(RequestAttempt.reserved_at).where(
            RequestAttempt.budget_name == budget.name,
            RequestAttempt.reserved_at > now - timedelta(seconds=rule.window_seconds)
        ).order_by(RequestAttempt.reserved_at.desc()).limit(rule.max_requests)))
        if len(recent) == rule.max_requests:
            deadlines.append(recent[-1] + timedelta(seconds=rule.window_seconds))
    return max(deadlines, default=None)


class BudgetRepository:
    def __init__(self, database_url):
        self.database_url = database_url

    def configure(self, name, *, min_interval_seconds, windows):
        """Update an existing budget atomically; never erase a reserved wait."""
        if type(min_interval_seconds) is not int or min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be a nonnegative integer")
        if not isinstance(windows, list):
            raise ValueError("windows must be a list")
        seen = set()
        for rule in windows:
            if not isinstance(rule, dict) or set(rule) != {"window_seconds", "max_requests"}:
                raise ValueError("Each window requires window_seconds and max_requests")
            if any(type(v) is not int or v <= 0 for v in rule.values()) or rule['window_seconds'] in seen:
                raise ValueError("Window durations must be unique and all values positive integers")
            seen.add(rule['window_seconds'])
        if name == "remotive" and min_interval_seconds < 21600:
            raise ValueError("Remotive budget requires at least 21600 seconds")
        session = get_session(self.database_url)
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            budget = session.get(RequestBudget, name)
            if budget is None:
                raise ValueError(f"Unknown budget {name!r}")
            from jobsearch.storage.source_repository import utcnow
            # Longer windows cannot be enforced accurately using already-pruned detail.
            for rule in windows:
                missing = session.scalar(select(DailyMetric.key).where(
                    DailyMetric.kind == 'request', DailyMetric.budget_name == name,
                    DailyMetric.last_event_at > utcnow() - timedelta(seconds=rule['window_seconds'])).limit(1))
                if missing:
                    raise ValueError('Requested budget window overlaps pruned request history')
            old_deadline = eligible_at(session, budget, utcnow())
            if old_deadline:
                budget.next_allowed_at = max(budget.next_allowed_at or old_deadline, old_deadline)
            budget.min_interval_seconds = min_interval_seconds
            if budget.last_attempt_at:
                deadline = budget.last_attempt_at + timedelta(seconds=min_interval_seconds)
                budget.next_allowed_at = max(budget.next_allowed_at or deadline, deadline)
            for old in session.scalars(select(RequestBudgetWindow).where(RequestBudgetWindow.budget_name == name)):
                session.delete(old)
            session.flush()
            session.add_all([RequestBudgetWindow(budget_name=name, **r) for r in windows])
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            close_session(session)
