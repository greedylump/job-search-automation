from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, String, Text, DateTime, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Job(Base):
    """Canonical raw job record for a single fetched opportunity."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("uq_jobs_source_source_job_id", "source", "source_job_id", unique=True),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_job_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    salary_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    salary_period: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    apply_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ats_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
