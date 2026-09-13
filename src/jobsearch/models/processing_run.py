from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProcessingRun(Base):
    """Tracks execution metrics for a collection-normalization-filtering metric run."""

    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_deduplicated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_filtered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_scored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
