"""
tests/unit/test_tracker.py — Unit tests for tracking and feedback loop.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assignment import Assignment
from app.models.email import Email
from app.models.employee import Employee
from app.models.enums import AssignmentStatus, TaskStatus
from app.models.task import Task
from app.models.task_history import TaskHistory
from app.services.tracker import (
    InvalidTransitionError,
    record_manual_rating,
    update_task_status,
    validate_transition,
)


@pytest.fixture
def tracker_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _setup_task_and_assignment(db, deadline=None, status=TaskStatus.ASSIGNED):
    email = Email(
        message_id=f"track-{uuid4()}@co.com",
        sender="lead@co.com",
        subject="Tracking Task",
        body="Do work",
        received_at=datetime.now(timezone.utc),
    )
    db.add(email)
    db.flush()

    task = Task(
        email_id=email.id,
        position=0,
        title="Tracked Task",
        deadline=deadline,
        priority="medium",
        required_skills=["python"],
        min_seniority="mid",
        category="data-analysis",
        status=status.value,
    )
    db.add(task)
    db.flush()

    emp = Employee(
        name="Tracked Emp",
        email="tracked@co.com",
        role="Dev",
        seniority="mid",
        skills=["python"],
        capacity=3,
        is_available=True,
    )
    db.add(emp)
    db.flush()

    assignment = Assignment(
        task_id=task.id,
        employee_id=emp.id,
        score=0.88,
        score_breakdown={},
        status=AssignmentStatus.ASSIGNED.value,
    )
    db.add(assignment)
    db.commit()
    db.refresh(task)
    db.refresh(assignment)
    return task, assignment, emp


def test_invalid_transition_rejected(tracker_db):
    """Transition from ASSIGNED directly to EXTRACTED is not allowed."""
    task, _, _ = _setup_task_and_assignment(tracker_db, status=TaskStatus.ASSIGNED)

    with pytest.raises(InvalidTransitionError):
        validate_transition(task.status, "extracted")


def test_completed_on_time_writes_history_and_rating(tracker_db):
    """
    When completed on time (before deadline):
    - on_time is True
    - auto_rating is 4.0
    - TaskHistory row is created
    """
    future_deadline = datetime.now(timezone.utc) + timedelta(days=2)
    task, assignment, emp = _setup_task_and_assignment(tracker_db, deadline=future_deadline)

    # Transition to in_progress first
    update_task_status(task.id, "in_progress", tracker_db)
    # Transition to completed
    completed_task, completed_assignment = update_task_status(task.id, "completed", tracker_db)

    assert completed_task.status == TaskStatus.COMPLETED.value
    assert completed_assignment.status == AssignmentStatus.COMPLETED.value
    assert completed_assignment.rating == 4.0

    # Verify task_history row
    history_rows = tracker_db.query(TaskHistory).filter_by(task_id=task.id).all()
    assert len(history_rows) == 1
    h = history_rows[0]
    assert h.employee_id == emp.id
    assert h.category == "data-analysis"
    assert h.rating == 4.0
    assert h.on_time is True


def test_completed_late_applies_lower_auto_rating(tracker_db):
    """
    When completed after deadline:
    - on_time is False
    - auto_rating is 2.0
    """
    past_deadline = datetime.now(timezone.utc) - timedelta(hours=5)
    task, assignment, _ = _setup_task_and_assignment(tracker_db, deadline=past_deadline)

    update_task_status(task.id, "in_progress", tracker_db)
    completed_task, completed_assignment = update_task_status(task.id, "completed", tracker_db)

    assert completed_task.status == TaskStatus.COMPLETED.value
    assert completed_assignment.rating == 2.0

    history_rows = tracker_db.query(TaskHistory).filter_by(task_id=task.id).all()
    assert len(history_rows) == 1
    assert history_rows[0].on_time is False
    assert history_rows[0].rating == 2.0


def test_reassignment_marks_active_assignment_superseded(tracker_db):
    """
    When a task is marked reassigned:
    - active assignment status becomes 'superseded'
    - task status becomes 'reassigned'
    - assign_task background job is queued with excluded previous employee id
    """
    task, assignment, emp = _setup_task_and_assignment(tracker_db, status=TaskStatus.ASSIGNED)

    with patch("worker.tasks.assign_task.delay") as mock_delay:
        updated_task, updated_assignment = update_task_status(task.id, "reassigned", tracker_db)

        assert updated_task.status == TaskStatus.REASSIGNED.value
        assert updated_assignment.status == AssignmentStatus.SUPERSEDED.value
        mock_delay.assert_called_once_with(str(task.id), exclude_employee_ids=[str(emp.id)])


def test_manual_rating_override(tracker_db):
    """Manual rating endpoint overrides both Assignment and TaskHistory ratings."""
    task, assignment, _ = _setup_task_and_assignment(tracker_db)

    update_task_status(task.id, "in_progress", tracker_db)
    update_task_status(task.id, "completed", tracker_db)

    # Override with manual 5.0 rating
    updated_assignment, updated_history = record_manual_rating(task.id, 5.0, tracker_db)

    assert updated_assignment.rating == 5.0
    assert updated_history.rating == 5.0

