"""
app/schemas/assignment.py — Pydantic schemas for assignments.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AssigneeSummary(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    seniority: str


class TaskSummary(BaseModel):
    id: UUID
    title: str
    priority: str
    deadline: Optional[datetime] = None
    required_skills: list[str] = []


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    employee_id: UUID
    score: float
    score_breakdown: dict[str, Any]
    reason: Optional[str] = None
    status: str
    assigned_at: datetime
    completed_at: Optional[datetime] = None
    rating: Optional[float] = None
    task: Optional[TaskSummary] = None
    assignee: Optional[AssigneeSummary] = None

