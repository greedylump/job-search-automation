from datetime import datetime
from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class CollectionControl(Base):
    __tablename__ = 'collection_control'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
