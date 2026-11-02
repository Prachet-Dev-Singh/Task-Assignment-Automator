"""
app/models/task_history.py — Completed-task performance feed for future scoring.

Written by tracker.py when a task reaches 'completed' status.
Read by scorer.py's performance signal to compute recency-weighted average
rating per employee per category.

category here must match the category stored in tasks — both are grounded
to the same vocabulary, so this join is reliable.
"""
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 1.0–5.0; set by auto-rating (on_time → 4.0, late → 2.0) or manual override
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    on_time: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    completed_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

