from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RequestAttempt(Base):
    """One committed request reservation; unfinished rows have unknown outcomes."""

    __tablename__ = "request_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    processing_run_id: Mapped[int] = mapped_column(ForeignKey("processing_runs.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(ForeignKey("job_sources.name"), nullable=False)
    budget_name: Mapped[str | None] = mapped_column(ForeignKey("request_budgets.name"), index=True)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    request_method: Mapped[str | None] = mapped_column(String(8))
    request_purpose: Mapped[str | None] = mapped_column(String(16))
    request_metadata: Mapped[dict | None] = mapped_column(JSON)
    response_bytes: Mapped[int | None] = mapped_column(Integer)
    records_returned: Mapped[int | None] = mapped_column(Integer)
    reserved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
