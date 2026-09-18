from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SearchPolicy(Base):
    __tablename__ = 'search_policies'
    __table_args__ = (CheckConstraint('revision >= 1', name='ck_policy_revision'),)
    applicant_id: Mapped[int] = mapped_column(ForeignKey('applicants.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TierStrategy(Base):
    __tablename__ = 'tier_strategies'
    __table_args__ = (
        UniqueConstraint('applicant_id', 'tier', name='uq_applicant_tier'),
        CheckConstraint("tier IN ('A','B','C','D')", name='ck_strategy_tier'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey('search_policies.applicant_id'), nullable=False)
    tier: Mapped[str] = mapped_column(String(1), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
