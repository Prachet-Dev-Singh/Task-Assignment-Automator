"""
app/models/assignment.py — Assignment decisions with full scoring trail.

The partial unique index (one active assignment per task) is defined in the
Alembic migration — SQLAlchemy UniqueConstraint cannot express a WHERE clause.

    CREATE UNIQUE INDEX uq_assignments_active_task
      ON assignments(task_id)
      WHERE status IN ('assigned', 'in_progress');

This prevents two Celery workers from both assigning the same task even if
the SELECT..FOR UPDATE in assigner.py is bypassed by a race.
"""
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import AssignmentStatus


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # Full per-signal breakdown stored as JSON for audit / future tuning
    score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=AssignmentStatus.ASSIGNED.value
    )
    assigned_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Populated by tracker.py (auto-rating or manual POST /tasks/{id}/rate)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)

