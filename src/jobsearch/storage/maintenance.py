"""Opt-in retention for a dedicated directory of disposable response snapshots."""
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jobsearch.config.settings import get_settings


def configure_worker_logging():
    total = int(os.getenv('JOBSEARCH_LOG_MAX_BYTES', '100000000'))
    if total < 10000:
        raise ValueError('JOBSEARCH_LOG_MAX_BYTES must be at least 10000')
    root = get_settings().data_dir / 'logs'
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'collection.log'
    logger = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == str(path.resolve()) for h in logger.handlers):
        handler = RotatingFileHandler(path, maxBytes=total // 10, backupCount=9, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)


def snapshots(directory, *, days=7, apply=False, now=None):
    """Only direct, regular .json files; no symlinks, recursion, or database files."""
    if days < 1:
        raise ValueError('Snapshot retention must be at least one day')
    root = Path(directory)
    resolved = root.resolve()
    if root.is_symlink() or resolved == resolved.parent:
        raise ValueError('Use a dedicated snapshot directory, not a symlink or filesystem root')
    cutoff = (time.time() if now is None else now) - days * 86400
    result = []
    if not root.exists():
        return result
    for path in sorted(root.glob('*.json')):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        if stat.st_mtime >= cutoff:
            continue
        result.append(dict(path=str(path.resolve()), bytes=stat.st_size))
        if apply:
            path.unlink()
    return result
