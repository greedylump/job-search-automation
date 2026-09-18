"""Bounded, transactional history rollup and deletion. Dry run by default."""
import hashlib
import json
from datetime import timedelta
from sqlalchemy import select, text, or_, and_, func
from jobsearch.models import DailyMetric, ProcessingRun, RequestAttempt, RequestBudgetWindow
from jobsearch.storage.database import get_session, close_session
from jobsearch.storage.source_repository import utcnow

TERMINAL = ('completed', 'failed', 'partial', 'deferred', 'skipped', 'paused', 'not_modified')
RUN_FIELDS = ('records_seen', 'jobs_new', 'jobs_deduplicated', 'records_invalid',
              'jobs_scored', 'ai_cost', 'pages_collected')
REQUEST_FIELDS = ('response_bytes', 'records_returned')


def rollup(session, row, kind):
    stamp = row.reserved_at if kind == 'request' else row.started_at
    dimensions = (dict(outcome=row.outcome, http_status=row.http_status,
                       purpose=row.request_purpose, budget_name=row.budget_name)
                  if kind == 'request' else dict(status=row.status, collection_mode=row.collection_mode))
    day = stamp.date().isoformat()
    key = hashlib.sha256(json.dumps([day, row.source, kind, dimensions], sort_keys=True).encode()).hexdigest()
    metric = session.get(DailyMetric, key)
    if metric is None:
        metric = DailyMetric(key=key, day=day, source=row.source, kind=kind,
            budget_name=row.budget_name if kind == 'request' else None,
            dimensions=dimensions, rows=0, totals={}, last_event_at=stamp)
        session.add(metric)
    totals = dict(metric.totals)
    for field in REQUEST_FIELDS if kind == 'request' else RUN_FIELDS:
        value = getattr(row, field)
        if value is not None:
            totals[field] = totals.get(field, 0) + value
            totals[field + '_known_rows'] = totals.get(field + '_known_rows', 0) + 1
    if kind == 'run':
        if row.invalid_reason_counts is not None:
            totals['invalid_reason_counts_known_rows'] = totals.get('invalid_reason_counts_known_rows', 0) + 1
        for reason, count in (row.invalid_reason_counts or {}).items():
            name = 'invalid_reason:' + reason
            totals[name] = totals.get(name, 0) + count
    elapsed = max(0, (row.completed_at - stamp).total_seconds())
    totals['elapsed_seconds'] = totals.get('elapsed_seconds', 0) + elapsed
    metric.totals = totals
    metric.rows += 1
    metric.last_event_at = max(metric.last_event_at, stamp)
    session.flush()  # Make the group visible to subsequent rows with autoflush disabled.


def retain_history(database_url, *, request_days=180, run_days=365, limit=1000, apply=False, now=None):
    if any(type(v) is not int or v < 1 for v in (request_days, run_days, limit)) or limit > 10000:
        raise ValueError('Retention days must be positive; batch limit must be 1–10000')
    now = now or utcnow()
    session = get_session(database_url)
    try:
        # Same lock as request reservations: quota-relevant rows cannot disappear mid-check.
        session.execute(text('BEGIN IMMEDIATE' if apply else 'BEGIN'))
        windows = dict(session.execute(select(RequestBudgetWindow.budget_name,
            func.max(RequestBudgetWindow.window_seconds)).group_by(RequestBudgetWindow.budget_name)).all())
        protected = [and_(RequestAttempt.budget_name == name,
                         RequestAttempt.reserved_at >= now - timedelta(seconds=seconds))
                     for name, seconds in windows.items()]
        query = select(RequestAttempt).join(ProcessingRun).where(
            RequestAttempt.reserved_at < now - timedelta(days=request_days),
            RequestAttempt.completed_at < now - timedelta(days=request_days),
            RequestAttempt.outcome != 'reserved',
            RequestAttempt.next_allowed_at <= now,
            or_(RequestAttempt.retry_at.is_(None), RequestAttempt.retry_at <= now),
            ProcessingRun.completed_at.is_not(None), ProcessingRun.status.in_(TERMINAL))
        if protected:
            query = query.where(~or_(*protected))
        attempts = list(session.scalars(query.order_by(RequestAttempt.id).limit(limit)))
        ids = [row.id for row in attempts]
        # Preview parent deletion as if the selected attempts had been removed.
        children = select(RequestAttempt.id).where(RequestAttempt.processing_run_id == ProcessingRun.id)
        if ids:
            children = children.where(RequestAttempt.id.not_in(ids))
        runs = list(session.scalars(select(ProcessingRun).where(
            ProcessingRun.started_at < now - timedelta(days=run_days),
            ProcessingRun.completed_at < now - timedelta(days=run_days),
            ProcessingRun.status.in_(TERMINAL), ~children.exists())
            .order_by(ProcessingRun.id).limit(limit)))
        def summarize(rows, field):
            stamps = [getattr(row, field) for row in rows]
            return dict(count=len(rows), ids=[row.id for row in rows],
                        first=min(stamps).isoformat() if stamps else None,
                        last=max(stamps).isoformat() if stamps else None)
        report = dict(applied=apply, request_days=request_days, run_days=run_days,
                      limit_per_table=limit, requests=summarize(attempts, 'reserved_at'),
                      runs=summarize(runs, 'started_at'))
        if apply:
            for row in attempts:
                rollup(session, row, 'request')
                session.delete(row)
            session.flush()
            for row in runs:
                rollup(session, row, 'run')
                session.delete(row)
            session.commit()
        else:
            session.rollback()
        return report
    finally:
        close_session(session)
