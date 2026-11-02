"""
app/schemas/employee.py — Pydantic schemas for employees.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmployeeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    role: str = Field(..., min_length=1)
    seniority: str = Field(..., pattern="^(junior|mid|senior|lead)$")
    skills: list[str] = Field(default_factory=list)
    capacity: int = Field(default=3, ge=1)
    is_available: bool = True


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    seniority: Optional[str] = Field(None, pattern="^(junior|mid|senior|lead)$")
    skills: Optional[list[str]] = None
    capacity: Optional[int] = Field(None, ge=1)
    is_available: Optional[bool] = None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    role: str
    seniority: str
    skills: list[str] = []
    capacity: int
    is_available: bool
    active_tasks: int = 0
    created_at: datetime

