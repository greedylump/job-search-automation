from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RequestBudget(Base):
    """Shared provider/account budget, independent of board refresh schedules."""
    __tablename__ = "request_budgets"
    __table_args__ = (CheckConstraint("min_interval_seconds >= 0", name="ck_budget_interval"),)

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)


class RequestBudgetWindow(Base):
    """Rolling window: every reservation, including failed requests, consumes quota."""
    __tablename__ = "request_budget_windows"
    __table_args__ = (
        CheckConstraint("window_seconds > 0", name="ck_window_seconds"),
        CheckConstraint("max_requests > 0", name="ck_window_requests"),
    )

    budget_name: Mapped[str] = mapped_column(ForeignKey("request_budgets.name"), primary_key=True)
    window_seconds: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_requests: Mapped[int] = mapped_column(Integer, nullable=False)
