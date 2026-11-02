"""
tests/integration/test_constraints.py — Integration tests for capacity & eligibility constraints.
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
from app.models.enums import AssignmentStatus, TaskStatus
from app.models.task import Task
from app.services.assigner import NoEligibleCandidateError, assign
from app.services.scorer import score_candidate


@pytest.fixture
def sync_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_when_all_employees_at_capacity_status_becomes_unassigned_no_eligible(sync_db):
    """
    When all employees are at capacity, assigner marks task as unassigned_no_eligible
    and raises NoEligibleCandidateError.
    """
    email = Email(
        message_id=f"constraint-{uuid4()}@company.com",
        sender="lead@co.com",
        subject="Busy Team",
        body="Work needed",
        received_at=datetime.now(timezone.utc),
    )
    sync_db.add(email)
    sync_db.flush()

    task = Task(
        email_id=email.id,
        position=0,
        title="Critical Task",
        priority="high",
        required_skills=["python"],
        min_seniority="mid",
        category="software-development",
        status=TaskStatus.EXTRACTED.value,
    )
    sync_db.add(task)

    emp = Employee(
        name="Busy Employee",
        email="busy@co.com",
        role="Dev",
        seniority="mid",
        skills=["python"],
        capacity=1,
        is_available=True,
    )
    sync_db.add(emp)
    sync_db.commit()

    # Employee already has 1 active assignment (at capacity of 1)
    past_task = Task(
        email_id=email.id,
        position=1,
        title="Prior Task",
        status=TaskStatus.ASSIGNED.value,
    )
    sync_db.add(past_task)
    sync_db.flush()

    active_assign = Assignment(
        task_id=past_task.id,
        employee_id=emp.id,
        score=0.9,
        score_breakdown={},
        status=AssignmentStatus.ASSIGNED.value,
    )
    sync_db.add(active_assign)
    sync_db.commit()

    # Score candidates
    scored = [
        score_candidate(
            task_required_skills=task.required_skills,
            task_min_seniority=task.min_seniority,
            task_category=task.category,
            task_deadline=task.deadline,
            emp_id=emp.id,
            emp_skills=emp.skills,
            emp_seniority=emp.seniority,
            emp_capacity=emp.capacity,
            emp_active_count=1,  # 1 of 1 slot used -> avail = 0.0 -> score = 0.0
            history_records=[],
        )
    ]

    assert scored[0]["score"] == 0.0

    with pytest.raises(NoEligibleCandidateError):
        assign(task, scored, sync_db)

    sync_db.refresh(task)
    assert task.status == TaskStatus.UNASSIGNED_NO_ELIGIBLE.value

