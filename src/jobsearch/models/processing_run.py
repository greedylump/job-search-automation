from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, String, Integer, DateTime, Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProcessingRun(Base):
    """Tracks execution metrics for a collection-normalization-filtering metric run."""

    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    records_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_deduplicated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_invalid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_reason_counts: Mapped[Optional[dict[str, int]]] = mapped_column(JSON, nullable=True)
    jobs_scored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
