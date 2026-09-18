from datetime import datetime
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class DailyMetric(Base):
    """Additive metrics for deleted history only; combine with remaining detail rows."""
    __tablename__ = 'daily_metrics'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    budget_name: Mapped[str | None] = mapped_column(String(64), index=True)
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_event_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
