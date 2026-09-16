"""Fail-closed storage checks and durable, explicitly resumed collection pauses.

Limits use decimal bytes. Configure extra owned directories with a JSON array;
never include a shared filesystem root as an application storage directory.
"""
import json
import logging
import os
import shutil
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from jobsearch.collectors.source import SourceSkipped
from jobsearch.config.settings import get_settings
from jobsearch.storage.database import get_session, close_session

logger = logging.getLogger(__name__)
_warnings = {}


def limits():
    values = {name: int(os.getenv('JOBSEARCH_' + name, default)) for name, default in {
        'STORAGE_MAX_BYTES': 8_000_000_000,
        'STORAGE_WARN_BYTES': 6_000_000_000,
        'DISK_MIN_FREE_BYTES': 5_000_000_000,
        'DISK_WARN_FREE_BYTES': 7_000_000_000,
    }.items()}
    if any(v <= 0 for v in values.values()):
        raise ValueError('Storage thresholds must be positive')
    if values['STORAGE_WARN_BYTES'] > values['STORAGE_MAX_BYTES'] or values['DISK_WARN_FREE_BYTES'] < values['DISK_MIN_FREE_BYTES']:
        raise ValueError('Storage warning thresholds must precede hard limits')
    return values


def measure(database_url):
    policy = limits()
    extra = json.loads(os.getenv('JOBSEARCH_STORAGE_DIRS', '[]'))
    if not isinstance(extra, list) or any(not isinstance(p, str) or not p for p in extra):
        raise ValueError('JOBSEARCH_STORAGE_DIRS must be a JSON array of directory paths')
    roots = [get_settings().data_dir.resolve(), *(Path(p).resolve() for p in extra)]
    files = set()
    volumes = set()
    for root in roots:
        if root.exists():
            if not root.is_dir():
                raise ValueError(f'Storage directory is not a directory: {root}')
            for folder, dirs, names in os.walk(root, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
                if any(Path(folder, d).is_symlink() for d in dirs + names):
                    raise OSError('Symlinks inside storage directories prevent reliable accounting')
                for name in names:
                    path = Path(folder, name)
                    if not path.is_symlink():
                        files.add(path.resolve())
        parent = root
        while not parent.exists():
            parent = parent.parent
        volumes.add(parent)
    url = make_url(database_url)
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
        raise ValueError('Storage guard requires a file-backed SQLite database')
    db = Path(url.database).resolve()
    for suffix in ('', '-wal', '-shm', '-journal'):
        path = Path(str(db) + suffix)
        if path.exists():
            files.add(path)
    volumes.add(db.parent)
    used = 0
    devices = set()
    for path in files:
        try:
            stat = path.stat()
            used += stat.st_size
            if stat.st_dev not in devices:
                volumes.add(path.parent)
                devices.add(stat.st_dev)
        except FileNotFoundError:
            pass  # A rotated log/journal may disappear during inspection.
    free = min(shutil.disk_usage(path).free for path in volumes)
    reason = ('disk_free_below_minimum' if free < policy['DISK_MIN_FREE_BYTES'] else
              'app_storage_limit_reached' if used >= policy['STORAGE_MAX_BYTES'] else None)
    return dict(app_bytes=used, free_bytes=free, limits=policy, threshold_reason=reason,
                storage_dirs=[str(p) for p in roots],
                warning=used >= policy['STORAGE_WARN_BYTES'] or free < policy['DISK_WARN_FREE_BYTES'])


def control(database_url, action='status', reason='manual_pause'):
    session = get_session(database_url)
    try:
        session.execute(text('BEGIN IMMEDIATE'))
        previous = session.execute(text('SELECT reason FROM collection_control WHERE id=1')).scalar_one()
        try:
            report = measure(database_url)
        except (OSError, ValueError) as exc:
            report = dict(threshold_reason='storage_check_failed', error=str(exc), warning=True)
        current = previous or report['threshold_reason']
        if action == 'pause':
            current = reason
        elif action == 'resume':
            current = report['threshold_reason']
        elif action != 'status':
            raise ValueError('Unknown collection control action')
        if current != previous:
            session.execute(text('UPDATE collection_control SET reason=:reason, updated_at=CURRENT_TIMESTAMP WHERE id=1'), {'reason': current})
            logger.warning('Collection state changed: %s -> %s', previous or 'enabled', current or 'enabled')
        session.commit()
        if report['warning'] and not _warnings.get(database_url):
            logger.warning('Storage warning: %s', report)
        _warnings[database_url] = report['warning']
        return dict(report, paused=current is not None, reason=current)
    finally:
        close_session(session)


def ensure_collection_allowed(database_url):
    report = control(database_url)
    if report['paused']:
        raise SourceSkipped('Collection paused: ' + report['reason'], None, status='paused')
    return report
