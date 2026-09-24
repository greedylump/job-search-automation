from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Index, String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class JobEvaluation(Base):
    """Future evaluation record that remains separate from the source job record."""

    __tablename__ = "job_evaluations"
    __table_args__ = (Index("uq_evaluation_inputs", "job_id", "applicant_id", "input_fingerprint", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    applicant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("applicants.id"), nullable=True, index=True)
    tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    hireability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    career_value_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    income_value_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    application_friction_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommended_resume_variant: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tailoring_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    queue_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    estimated_ai_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    rules_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    input_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reasons: Mapped[Optional[list[dict]]] = mapped_column(JSON, nullable=True)
    input_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    job = relationship("Job")
    applicant = relationship("Applicant", back_populates="evaluations")
