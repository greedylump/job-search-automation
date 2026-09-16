from contextvars import ContextVar

# Scoped to the collection callback, including legacy snapshot wrappers.
processing_run_id: ContextVar[int | None] = ContextVar("processing_run_id", default=None)
collector_lease: ContextVar[str | None] = ContextVar("collector_lease", default=None)
