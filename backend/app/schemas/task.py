"""
app/schemas/task.py — Pydantic schemas for tasks.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email_id: UUID
    position: int
    title: str
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    priority: str
    required_skills: list[str] = []
    unmapped_skills: list[str] = []
    min_seniority: str
    category: Optional[str] = None
    llm_confidence: Optional[float] = None
    status: str
    created_at: datetime


class TaskStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="Target status (e.g. in_progress, completed, reassigned, cancelled)")


class TaskRateRequest(BaseModel):
    rating: float = Field(..., ge=1.0, le=5.0, description="Manual rating between 1.0 and 5.0")


class TaskApproveRequest(BaseModel):
    """Payload for human reviewer approving a review_required task."""
    title: Optional[str] = Field(None, description="Adjusted task title if needed")
    required_skills: Optional[list[str]] = Field(None, description="Corrected or confirmed required skills")
    min_seniority: Optional[str] = Field(None, pattern="^(junior|mid|senior|lead)$")


class TaskDetailResponse(TaskResponse):
    """Includes assignment details when available."""
    assignment: Optional[dict[str, Any]] = None

