"""Read collector eligibility and bounded request history without fetching jobs."""
from sqlalchemy import select, func

from jobsearch.models import JobSource, ProcessingRun, RequestAttempt, RequestBudget, RequestBudgetWindow
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.budget_repository import eligible_at
from jobsearch.storage.source_repository import utcnow
from jobsearch.storage.collection_control import control


def print_status(database_url: str, name: str | None, limit: int) -> None:
    state = control(database_url)
    print(f"Global collection: {'PAUSED' if state['paused'] else 'enabled'}; reason={state['reason'] or 'none'}")
    session = get_session(database_url)
    try:
        configs = list(session.scalars(select(JobSource).order_by(JobSource.name)))
        selected = [c for c in configs if name is None or c.name == name]
        if name is not None and not selected:
            raise ValueError(f"Collector {name!r} does not exist")
        if not selected:
            print("No configured collectors.")
        for config in selected:
            budget = session.get(RequestBudget, config.budget_name) if config.budget_name else None
            budget_deadline = eligible_at(session, budget, utcnow()) if budget else None
            deadlines = [d for d in (budget_deadline, config.next_due_at) if d is not None]
            deadline = max(deadlines, default=None)
            print(f"{config.name} ({config.adapter_type}): enabled={config.enabled}; "
                  f"next eligible UTC={deadline or 'no outstanding wait'}")
            print(f"  Refresh interval={config.refresh_interval_seconds}s; next due UTC={config.next_due_at}; "
                  f"last complete UTC={config.last_complete_refresh_at}")
            print(f"  Continuation saved={config.continuation is not None}; lease expires UTC={config.lease_expires_at}")
            if budget:
                print(f"  Budget={budget.name}; request spacing={budget.min_interval_seconds}s; "
                      f"budget eligible UTC={budget_deadline}")
                for rule in session.scalars(select(RequestBudgetWindow).where(RequestBudgetWindow.budget_name == budget.name)):
                    print(f"    Rolling quota={rule.max_requests} requests/{rule.window_seconds}s")
            pending = session.scalar(select(func.count()).select_from(RequestAttempt).where(
                RequestAttempt.source == config.name, RequestAttempt.completed_at.is_(None)))
            print(f"  Reserved attempts total={config.request_attempts}; unfinished/unknown={pending}")
            rows = session.execute(select(RequestAttempt, ProcessingRun).join(
                ProcessingRun, RequestAttempt.processing_run_id == ProcessingRun.id).where(
                RequestAttempt.source == config.name).order_by(
                RequestAttempt.reserved_at.desc(), RequestAttempt.id.desc()).limit(limit)).all()
            if not rows:
                print("  No recorded HTTP attempts (legacy runs may predate tracking).")
            for attempt, run in rows:
                outcome = attempt.outcome if attempt.completed_at else "reserved (outcome unknown)"
                print(f"  Attempt {attempt.id}: {outcome}; HTTP={attempt.http_status}; "
                      f"reserved UTC={attempt.reserved_at}; completed UTC={attempt.completed_at}")
                print(f"    Retry UTC={attempt.retry_at}; next allowed UTC={attempt.next_allowed_at}")
                print(f"    Request={attempt.request_method or 'unknown'} {attempt.request_purpose or 'unknown'}; "
                      f"page metadata={attempt.request_metadata}; bytes={attempt.response_bytes}; "
                      f"records={attempt.records_returned}")
                print(f"    Run {run.id}: {run.status}; new={run.jobs_new}; "
                      f"duplicates={run.jobs_deduplicated}; invalid={run.records_invalid}")
            # Include skips and replays that intentionally have no HTTP attempt.
            runs = session.scalars(select(ProcessingRun).where(ProcessingRun.source == config.name)
                .order_by(ProcessingRun.started_at.desc(), ProcessingRun.id.desc()).limit(limit))
            for run in runs:
                print(f"  Recent run {run.id}: {run.status}; mode={run.collection_mode or 'unknown'}; "
                      f"new={run.jobs_new}; duplicates={run.jobs_deduplicated}; invalid={run.records_invalid}; pages={run.pages_collected}")
                if run.skip_reason:
                    print(f"    {run.skip_reason}; next eligible UTC={run.next_eligible_at}")
    finally:
        close_session(session)
