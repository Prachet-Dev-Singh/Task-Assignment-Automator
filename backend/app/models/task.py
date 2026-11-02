"""
app/models/task.py — LLM-extracted task records.

position: index of this task within the originating email (0-based).
  Combined with email_id in a UNIQUE constraint to prevent duplicate Task rows
  if process_email is retried (Celery at-least-once delivery).

unmapped_skills: skills the LLM identified as needed but that are NOT in the
  org's canonical skill vocabulary. Stored so a task needing an unlisted skill
  is flagged rather than silently ignored.

TaskStatus.PENDING is intentionally absent — tasks are never in a pending
state. They are created directly as EXTRACTED or REVIEW_REQUIRED.
"""
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import TaskStatus


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Idempotency: retried process_email cannot create duplicate tasks
        UniqueConstraint("email_id", "position", name="uq_tasks_email_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id"), nullable=False
    )
    # 0-based index within the email (multi-task emails produce position 0, 1, 2, ...)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(String, nullable=False, default="medium")

    # Skills from the org vocabulary that this task requires
    required_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    # Skills identified by the LLM that are NOT in the org vocabulary
    # Stored for flagging/auditing — not used in scoring
    unmapped_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    min_seniority: Mapped[str] = mapped_column(String, nullable=False, default="mid")
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=TaskStatus.EXTRACTED.value
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

