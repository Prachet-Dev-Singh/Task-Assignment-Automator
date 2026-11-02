"""
tests/unit/test_assigner.py — Unit tests for assignment engine.

Tests candidate selection, tie-breaking, OOO skipping, self-assignment block,
reassignment exclusions, and failure handling.
"""

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


@pytest.fixture
def db_session():
    """In-memory SQLite session with table structures created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _create_sample_task(db_session, required_skills=None) -> Task:
    email = Email(
        message_id=f"msg-{uuid4()}@co.com",
        sender="boss@company.com",
        subject="Project Task",
        body="Do this task",
        received_at=None,
    )
    # Give a dummy datetime string for sqlite
    from datetime import datetime, timezone
    email.received_at = datetime.now(timezone.utc)
    db_session.add(email)
    db_session.flush()

    task = Task(
        email_id=email.id,
        position=0,
        title="Sample Task",
        required_skills=required_skills or ["python", "sql"],
        min_seniority="mid",
        category="data-analysis",
        status=TaskStatus.EXTRACTED.value,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def test_assign_picks_highest_scoring_eligible(db_session):
    """Assigner picks the highest scoring candidate."""
    task = _create_sample_task(db_session)

    emp1 = Employee(
        name="Candidate One",
        email="c1@co.com",
        role="Dev",
        seniority="mid",
        skills=["python"],
        capacity=3,
        is_available=True,
    )
    emp2 = Employee(
        name="Candidate Two",
        email="c2@co.com",
        role="Dev",
        seniority="mid",
        skills=["python", "sql"],
        capacity=3,
        is_available=True,
    )
    db_session.add_all([emp1, emp2])
    db_session.commit()

    scored = [
        {"employee_id": emp1.id, "score": 0.65, "breakdown": {"skills": 0.5}, "details": {"active_count": 0}},
        {"employee_id": emp2.id, "score": 0.95, "breakdown": {"skills": 1.0}, "details": {"active_count": 0}},
    ]

    assignment = assign(task, scored, db_session)

    assert assignment.employee_id == emp2.id
    assert assignment.score == 0.95
    assert task.status == TaskStatus.ASSIGNED.value
    assert "Skills:" in assignment.reason


def test_assign_tie_broken_by_lower_load(db_session):
    """When scores are tied, employee with fewer active tasks is picked."""
    task = _create_sample_task(db_session)

    emp1 = Employee(name="Busy Emp", email="busy@co.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    emp2 = Employee(name="Free Emp", email="free@co.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    db_session.add_all([emp1, emp2])
    db_session.commit()

    scored = [
        {"employee_id": emp1.id, "score": 0.85, "breakdown": {}, "details": {"active_count": 2}},
        {"employee_id": emp2.id, "score": 0.85, "breakdown": {}, "details": {"active_count": 0}},
    ]

    assignment = assign(task, scored, db_session)

    # Free Emp should win the tie-break
    assert assignment.employee_id == emp2.id


def test_assign_skips_ooo_employee(db_session):
    """Candidate with is_available = False is skipped even if top scorer."""
    task = _create_sample_task(db_session)

    emp_ooo = Employee(name="OOO Emp", email="ooo@co.com", role="Dev", seniority="senior", capacity=3, is_available=False)
    emp_avail = Employee(name="Active Emp", email="active@co.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    db_session.add_all([emp_ooo, emp_avail])
    db_session.commit()

    scored = [
        {"employee_id": emp_ooo.id, "score": 0.98, "breakdown": {}, "details": {"active_count": 0}},
        {"employee_id": emp_avail.id, "score": 0.70, "breakdown": {}, "details": {"active_count": 0}},
    ]

    assignment = assign(task, scored, db_session)

    assert assignment.employee_id == emp_avail.id


def test_assign_skips_self_assignment(db_session):
    """Requester email is skipped to avoid self-assignment."""
    task = _create_sample_task(db_session)

    emp_sender = Employee(name="Requester", email="boss@company.com", role="Lead", seniority="lead", capacity=3, is_available=True)
    emp_other = Employee(name="Team Member", email="worker@company.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    db_session.add_all([emp_sender, emp_other])
    db_session.commit()

    scored = [
        {"employee_id": emp_sender.id, "score": 0.99, "breakdown": {}, "details": {"active_count": 0}},
        {"employee_id": emp_other.id, "score": 0.75, "breakdown": {}, "details": {"active_count": 0}},
    ]

    assignment = assign(task, scored, db_session, exclude_emails=["boss@company.com"])

    assert assignment.employee_id == emp_other.id


def test_assign_skips_excluded_employee_on_reassignment(db_session):
    """When a task is reassigned, the previous assignee is excluded."""
    task = _create_sample_task(db_session)

    emp_prev = Employee(name="Previous Assignee", email="prev@co.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    emp_new = Employee(name="New Assignee", email="new@co.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    db_session.add_all([emp_prev, emp_new])
    db_session.commit()

    scored = [
        {"employee_id": emp_prev.id, "score": 0.90, "breakdown": {}, "details": {"active_count": 0}},
        {"employee_id": emp_new.id, "score": 0.80, "breakdown": {}, "details": {"active_count": 0}},
    ]

    assignment = assign(task, scored, db_session, exclude_employee_ids=[emp_prev.id])

    assert assignment.employee_id == emp_new.id


def test_assign_raises_when_no_eligible_candidate(db_session):
    """If all candidates scored 0.0, sets unassigned_no_eligible and raises error."""
    task = _create_sample_task(db_session)

    emp = Employee(name="Overloaded Emp", email="over@co.com", role="Dev", seniority="mid", capacity=3, is_available=True)
    db_session.add(emp)
    db_session.commit()

    scored = [
        {"employee_id": emp.id, "score": 0.0, "breakdown": {"availability": 0.0}, "details": {}}
    ]

    with pytest.raises(NoEligibleCandidateError):
        assign(task, scored, db_session)

    db_session.refresh(task)
    assert task.status == TaskStatus.UNASSIGNED_NO_ELIGIBLE.value

