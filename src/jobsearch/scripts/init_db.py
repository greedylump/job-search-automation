from __future__ import annotations

import logging

from jobsearch.config.settings import settings
from jobsearch.storage.database import init_db

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


if __name__ == "__main__":
    init_db(settings.database_url)
