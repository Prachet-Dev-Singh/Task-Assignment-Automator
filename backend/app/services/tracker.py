"""
app/services/tracker.py — Stage 6: Tracking & Feedback Loop.

Handles task lifecycle transitions, status updates, completion rating calculations,
task_history persistence for future scoring, and reassignment workflow.

Key responsibilities:
  - Validates state transitions using VALID_TRANSITIONS from app.models.enums.
  - On COMPLETED:
      - Computes on_time (completed_at <= deadline).
      - Applies auto-rating (AUTO_RATING_ON_TIME or AUTO_RATING_LATE).
      - Writes a TaskHistory row consumed by scorer.py's performance signal.
      - Marks Assignment as COMPLETED.
  - On REASSIGNED:
      - Marks current assignment as SUPERSEDED.
      - Sets Task status to REASSIGNED.
      - Enqueues assign_task(task_id, exclude_employee_ids=[prev_assignee_id]).
        NOTE: Does NOT call process_email (prevents duplicate LLM extraction).
  - Manual rating override: updates rating in Assignment and TaskHistory.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.assignment import Assignment
from app.models.enums import (
    ACTIVE_TASK_STATUSES,
    AssignmentStatus,
    TaskStatus,
    VALID_TRANSITIONS,
)
from app.models.task import Task
from app.models.task_history import TaskHistory
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is requested."""
    def __init__(self, current_status: str, target_status: str, allowed: list[str]):
        self.current_status = current_status
        self.target_status = target_status
        self.allowed = allowed
        super().__init__(
            f"Cannot transition task from '{current_status}' to '{target_status}'. "
            f"Allowed transitions: {allowed}"
        )


def validate_transition(current_status: str, target_status: str) -> TaskStatus:
    """Validate that transition is allowed by the VALID_TRANSITIONS state machine."""
    try:
        curr_enum = TaskStatus(current_status.lower().strip())
        target_enum = TaskStatus(target_status.lower().strip())
    except ValueError as e:
        raise ValueError(f"Invalid status value: {e}") from e

    allowed = VALID_TRANSITIONS.get(curr_enum, frozenset())
    if target_enum not in allowed:
        raise InvalidTransitionError(
            current_status=curr_enum.value,
            target_status=target_enum.value,
            allowed=[s.value for s in allowed],
        )
    return target_enum


def update_task_status(
    task_id: UUID | str,
    target_status: str,
    db: Session,
    completed_at: Optional[datetime] = None,
) -> tuple[Task, Optional[Assignment]]:
    """
    Execute a validated task status transition.

    Args:
        task_id:        Task UUID or string.
        target_status:  Desired new status string.
        db:             Synchronous SQLAlchemy session.
        completed_at:   Optional completion timestamp (defaults to now UTC).

    Returns:
        Tuple of (updated Task, updated or active Assignment).
    """
    t_uuid = UUID(str(task_id)) if not isinstance(task_id, UUID) else task_id
    task = db.get(Task, t_uuid)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    target_enum = validate_transition(task.status, target_status)
    now = completed_at or datetime.now(timezone.utc)

    # Fetch latest active or associated assignment
    stmt = (
        select(Assignment)
        .where(Assignment.task_id == task.id)
        .order_by(Assignment.assigned_at.desc())
    )
    assignment = db.execute(stmt).scalars().first()

    # ── Handle COMPLETED ──────────────────────────────────────────────────────
    if target_enum == TaskStatus.COMPLETED:
        # Determine on_time
        if task.deadline:
            d_tz = task.deadline if task.deadline.tzinfo else task.deadline.replace(tzinfo=timezone.utc)
            n_tz = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            on_time = n_tz <= d_tz
        else:
            on_time = True

        auto_rating = (
            settings.AUTO_RATING_ON_TIME if on_time else settings.AUTO_RATING_LATE
        )

        if assignment:
            assignment.status = AssignmentStatus.COMPLETED.value
            assignment.completed_at = now
            assignment.rating = auto_rating

            # Write TaskHistory row for future scoring
            history = TaskHistory(
                employee_id=assignment.employee_id,
                task_id=task.id,
                category=task.category,
                rating=auto_rating,
                on_time=on_time,
                completed_at=now,
            )
            db.add(history)

        task.status = TaskStatus.COMPLETED.value
        db.commit()
        db.refresh(task)
        if assignment:
            db.refresh(assignment)
        return task, assignment

    # ── Handle CANCELLED ──────────────────────────────────────────────────────
    elif target_enum == TaskStatus.CANCELLED:
        if assignment and assignment.status in [s.value for s in ACTIVE_TASK_STATUSES]:
            assignment.status = AssignmentStatus.CANCELLED.value
            assignment.completed_at = now

        task.status = TaskStatus.CANCELLED.value
        db.commit()
        db.refresh(task)
        if assignment:
            db.refresh(assignment)
        return task, assignment

    # ── Handle REASSIGNED ─────────────────────────────────────────────────────
    elif target_enum == TaskStatus.REASSIGNED:
        prev_employee_id = None
        if assignment and assignment.status in [s.value for s in ACTIVE_TASK_STATUSES]:
            assignment.status = AssignmentStatus.SUPERSEDED.value
            assignment.completed_at = now
            prev_employee_id = assignment.employee_id

        task.status = TaskStatus.REASSIGNED.value
        db.commit()
        db.refresh(task)

        # Enqueue assign_task only (does NOT re-run LLM extraction)
        exclude_ids = [str(prev_employee_id)] if prev_employee_id else []
        try:
            from worker.tasks import assign_task
            assign_task.delay(str(task.id), exclude_employee_ids=exclude_ids)
        except Exception as e:
            logger.warning(f"failed_to_enqueue_reassignment: task_id={task.id}, error={e}")

        return task, assignment

    # ── Handle IN_PROGRESS / EXTRACTED ────────────────────────────────────────
    else:
        task.status = target_enum.value
        if assignment and target_enum == TaskStatus.IN_PROGRESS:
            assignment.status = AssignmentStatus.IN_PROGRESS.value

        db.commit()
        db.refresh(task)
        if assignment:
            db.refresh(assignment)
        return task, assignment


def record_manual_rating(task_id: UUID | str, rating: float, db: Session) -> tuple[Assignment, Optional[TaskHistory]]:
    """
    Record or override a manual performance rating (1.0 to 5.0) for a completed task.
    Updates both the Assignment record and the TaskHistory record.
    """
    if rating < 1.0 or rating > 5.0:
        raise ValueError(f"Rating {rating} out of valid range (1.0 to 5.0)")

    t_uuid = UUID(str(task_id)) if not isinstance(task_id, UUID) else task_id

    # Fetch assignment
    assign_stmt = (
        select(Assignment)
        .where(Assignment.task_id == t_uuid)
        .order_by(Assignment.assigned_at.desc())
    )
    assignment = db.execute(assign_stmt).scalars().first()
    if not assignment:
        raise ValueError(f"No assignment found for task {task_id}")

    assignment.rating = round(rating, 2)

    # Fetch corresponding task_history row
    hist_stmt = (
        select(TaskHistory)
        .where(TaskHistory.task_id == t_uuid)
        .where(TaskHistory.employee_id == assignment.employee_id)
    )
    history = db.execute(hist_stmt).scalars().first()
    if history:
        history.rating = round(rating, 2)
    else:
        # Create history record if not already written
        history = TaskHistory(
            employee_id=assignment.employee_id,
            task_id=t_uuid,
            category=None,
            rating=round(rating, 2),
            on_time=True,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(history)

    db.commit()
    db.refresh(assignment)
    db.refresh(history)
    return assignment, history

