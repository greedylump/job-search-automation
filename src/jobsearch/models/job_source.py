from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.mutable import MutableDict

from .base import Base


class JobSource(Base):
    """Collection policy and request state, shared by all workers using this database."""

    __tablename__ = "job_sources"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), nullable=False, default=dict)
    budget_name: Mapped[str | None] = mapped_column(ForeignKey("request_budgets.name"))
    refresh_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_complete_refresh_at: Mapped[datetime | None] = mapped_column(DateTime)
    continuation: Mapped[dict | None] = mapped_column(JSON)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    collection_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    response_retention: Mapped[str] = mapped_column(String(32), nullable=False)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    request_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
