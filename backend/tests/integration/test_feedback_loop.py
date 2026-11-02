"""
tests/integration/test_feedback_loop.py — End-to-end feedback loop verification.

Verifies:
  1. Assign task -> Employee active capacity decreases.
  2. Complete task -> Employee active capacity recovers.
  3. Complete task -> task_history row written with performance rating.
  4. Next scoring run -> Performance signal reads updated history and shifts score.
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assignment import Assignment
from app.models.email import Email
from app.models.employee import Employee
from app.models.enums import TaskStatus
from app.models.task import Task
from app.models.task_history import TaskHistory
from app.services.assigner import assign, count_active_assignments
from app.services.scorer import score_candidate
from app.services.tracker import update_task_status


@pytest.fixture
def feedback_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_feedback_loop_updates_employee_scoring(feedback_db):
    """
    Complete lifecycle test proving the feedback loop:
    1. Employee has no history -> performance score is neutral 0.5.
    2. Employee completes a task with rating 2.0 (late).
    3. New task in same category -> Employee performance score drops to 0.40 (2/5).
    4. Active slot is freed up after completion.
    """
    # Create employee
    emp = Employee(
        name="Feedback Analyst",
        email="analyst@co.com",
        role="Data Analyst",
        seniority="mid",
        skills=["python", "sql", "powerbi"],
        capacity=2,
        is_available=True,
    )
    feedback_db.add(emp)

    email1 = Email(
        message_id=f"fb1-{uuid4()}@co.com",
        sender="lead@co.com",
        subject="Report 1",
        body="Do report",
        received_at=datetime.now(timezone.utc),
    )
    feedback_db.add(email1)
    feedback_db.flush()

    task1 = Task(
        email_id=email1.id,
        position=0,
        title="Q1 Report",
        required_skills=["powerbi"],
        min_seniority="mid",
        category="data-analysis",
        status=TaskStatus.EXTRACTED.value,
    )
    feedback_db.add(task1)
    feedback_db.commit()

    # Step 1: Initial scoring with 0 history -> perf = 0.5
    s1 = score_candidate(
        task_required_skills=task1.required_skills,
        task_min_seniority=task1.min_seniority,
        task_category=task1.category,
        task_deadline=task1.deadline,
        emp_id=emp.id,
        emp_skills=emp.skills,
        emp_seniority=emp.seniority,
        emp_capacity=emp.capacity,
        emp_active_count=count_active_assignments(emp.id, feedback_db),
        history_records=[],
    )
    assert s1["breakdown"]["performance"] == 0.5
    assert s1["breakdown"]["availability"] == 1.0  # 0 of 2 used

    # Step 2: Assign task 1
    assignment1 = assign(task1, [s1], feedback_db)
    assert count_active_assignments(emp.id, feedback_db) == 1

    # Step 3: Transition task1 to completed with past deadline (late -> rating 2.0)
    task1.deadline = datetime(2026, 1, 1, tzinfo=timezone.utc)  # past
    feedback_db.commit()

    update_task_status(task1.id, "in_progress", feedback_db)
    update_task_status(task1.id, "completed", feedback_db)

    # Verify active capacity recovered
    assert count_active_assignments(emp.id, feedback_db) == 0

    # Verify history recorded
    hist_records = feedback_db.query(TaskHistory).filter_by(employee_id=emp.id).all()
    assert len(hist_records) == 1
    assert hist_records[0].rating == 2.0
    assert hist_records[0].on_time is False

    # Step 4: Create new task in same category
    email2 = Email(
        message_id=f"fb2-{uuid4()}@co.com",
        sender="lead@co.com",
        subject="Report 2",
        body="Do report 2",
        received_at=datetime.now(timezone.utc),
    )
    feedback_db.add(email2)
    feedback_db.flush()

    task2 = Task(
        email_id=email2.id,
        position=0,
        title="Q2 Report",
        required_skills=["powerbi"],
        min_seniority="mid",
        category="data-analysis",
        status=TaskStatus.EXTRACTED.value,
    )
    feedback_db.add(task2)
    feedback_db.commit()

    # Step 5: Score employee for task2 reading live history
    s2 = score_candidate(
        task_required_skills=task2.required_skills,
        task_min_seniority=task2.min_seniority,
        task_category=task2.category,
        task_deadline=task2.deadline,
        emp_id=emp.id,
        emp_skills=emp.skills,
        emp_seniority=emp.seniority,
        emp_capacity=emp.capacity,
        emp_active_count=count_active_assignments(emp.id, feedback_db),
        history_records=hist_records,
    )

    # 2.0 rating out of 5.0 -> performance score is now 0.40 (down from 0.50 neutral)
    assert s2["breakdown"]["performance"] == 0.4
    assert s2["score"] < s1["score"]

