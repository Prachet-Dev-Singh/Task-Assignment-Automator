"""
app/models/employee.py — Employee profiles.

skills uses a GIN index (defined in the migration) for fast overlap queries.
Active load is NOT stored as a counter here — it is computed live by counting
assignments WHERE status IN ('assigned', 'in_progress'). This avoids counter
drift across retries and restarts.
"""
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # junior | mid | senior | lead
    seniority: Mapped[str] = mapped_column(String, nullable=False)
    # All tags must be lowercase and from the canonical vocabulary
    skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # False = out of office / unavailable — skipped before scoring
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

