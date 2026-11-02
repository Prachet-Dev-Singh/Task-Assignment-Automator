"""
app/models/__init__.py — Import all models so Alembic autogenerate can see them.
"""
from app.models.assignment import Assignment
from app.models.email import Email
from app.models.employee import Employee
from app.models.enums import (
    ACTIVE_TASK_STATUSES,
    VALID_TRANSITIONS,
    AssignmentStatus,
    EmailStatus,
    TaskStatus,
)
from app.models.task import Task
from app.models.task_history import TaskHistory

__all__ = [
    "Email",
    "Task",
    "Employee",
    "Assignment",
    "TaskHistory",
    "EmailStatus",
    "TaskStatus",
    "AssignmentStatus",
    "ACTIVE_TASK_STATUSES",
    "VALID_TRANSITIONS",
]

