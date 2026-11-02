"""
app/services/assigner.py — Stage 4: Assignment Engine.

Takes scored candidates, applies business constraints, locks the winner's
row to prevent race conditions, generates a plain-English reason string,
and records the assignment in the database.

Constraints enforced:
  - No overload: candidates with active_tasks >= capacity are skipped.
  - Seniority floor: candidates 2+ levels below min_seniority are disqualified.
  - Availability: is_available == False (OOO) candidates are skipped.
  - Self-assignment block: exclude_emails (e.g. email sender) are skipped.
  - Concurrency safety: SELECT ... FOR UPDATE (blocking row lock) on the employee.
    Re-checks capacity inside the lock to protect against concurrent assignments.
  - Tie-break: highest score first; ties broken by lower active task count.
"""

import logging
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.employee import Employee
from app.models.enums import ACTIVE_TASK_STATUSES, AssignmentStatus, TaskStatus
from app.models.task import Task

logger = logging.getLogger(__name__)


class NoEligibleCandidateError(Exception):
    """Raised when no candidate meets all constraints for assignment."""

    def __init__(self, task_id: Any, reason: str = "No eligible candidates found"):
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"Task {task_id}: {reason}")


def count_active_assignments(employee_id: UUID | str, db: Session) -> int:
    """
    Count live assignments consuming capacity for an employee.
    Uses ACTIVE_TASK_STATUSES = {ASSIGNED, IN_PROGRESS}.
    """
    target_id = employee_id
    if isinstance(target_id, str):
        try:
            target_id = UUID(target_id)
        except ValueError:
            pass

    stmt = (
        select(func.count(Assignment.id))
        .where(Assignment.employee_id == target_id)
        .where(Assignment.status.in_([s.value for s in ACTIVE_TASK_STATUSES]))
    )
    return db.execute(stmt).scalar() or 0


def build_reason_string(
    emp: Employee,
    task: Task,
    score_data: dict[str, Any],
    active_count: int,
) -> str:
    """Generate a plain-English explanation for why this employee was selected."""
    import json
    details = score_data.get("details", {})
    bd = score_data.get("breakdown", {})

    matched = details.get("matched_skills", [])
    raw_req = task.required_skills
    if isinstance(raw_req, (list, tuple)) and len(raw_req) > 0 and raw_req[0] == "[":
        try:
            raw_req = json.loads("".join(str(c) for c in raw_req))
        except Exception:
            pass
    elif isinstance(raw_req, str):
        try:
            raw_req = json.loads(raw_req)
        except Exception:
            raw_req = [raw_req]

    req_count = details.get("required_count", len(raw_req or []))
    matched_str = f" ({', '.join(sorted(matched))})" if matched else ""
    skills_part = f"Skills: {len(matched)}/{req_count} matched{matched_str}."

    capacity = details.get("capacity", emp.capacity)
    avail_part = f"Availability: {active_count} of {capacity} slots used."

    hist_count = details.get("history_count", 0)
    perf_val = bd.get("performance", 0.5) * 5.0
    if hist_count > 0:
        perf_part = f"Performance: avg {perf_val:.1f}/5.0 on {hist_count} similar {task.category or 'work'} tasks."
    else:
        perf_part = "Performance: 0.5 neutral (no past history in category)."

    gap = details.get("seniority_gap", 0)
    if gap >= 0:
        sen_text = f"{emp.seniority} meets/exceeds {task.min_seniority} requirement."
    else:
        sen_text = f"{emp.seniority} is one level below {task.min_seniority} requirement."
    sen_part = f"Seniority: {sen_text}"

    urgent_note = " [Urgency weight-shift applied]" if score_data.get("is_urgent_applied") else ""

    return f"{skills_part} {avail_part} {perf_part} {sen_part}{urgent_note}"


def assign(
    task: Task,
    scored_candidates: Sequence[dict[str, Any]],
    db: Session,
    exclude_emails: Sequence[str] | None = None,
    exclude_employee_ids: Sequence[UUID | str] | None = None,
) -> Assignment:
    """
    Assign the best-fit eligible candidate to a task.

    Args:
        task:                 Task ORM instance.
        scored_candidates:    Output list from score_candidate().
        db:                   Active synchronous SQLAlchemy session.
        exclude_emails:       List of emails to skip (e.g. requester email).
        exclude_employee_ids: List of employee IDs to skip (e.g. on reassignment).

    Returns:
        Persisted Assignment ORM instance.

    Raises:
        NoEligibleCandidateError if no candidate is eligible or all are locked/at capacity.
    """
    # 1. Filter out disqualified candidates (score == 0.0)
    eligible = [s for s in scored_candidates if s.get("score", 0.0) > 0.0]

    # 2. Exclude specific employee IDs (used during reassignment)
    if exclude_employee_ids:
        excluded_id_set = {str(eid) for eid in exclude_employee_ids}
        eligible = [s for s in eligible if str(s["employee_id"]) not in excluded_id_set]

    # 3. Sort by: score descending, then active_count ascending (tie-breaker)
    eligible.sort(
        key=lambda s: (
            -s.get("score", 0.0),
            s.get("details", {}).get("active_count", 0),
        )
    )

    if not eligible:
        task.status = TaskStatus.UNASSIGNED_NO_ELIGIBLE.value
        db.commit()
        raise NoEligibleCandidateError(
            task.id, reason="All candidates scored 0.0 or were disqualified by constraints."
        )

    norm_exclude_emails = {e.lower().strip() for e in (exclude_emails or [])}

    # 4. Attempt to lock and assign candidate in rank order
    bind = db.get_bind()
    supports_lock = getattr(bind.dialect, "supports_for_update", True) and bind.dialect.name != "sqlite"

    for candidate_score in eligible:
        emp_id = candidate_score["employee_id"]
        if isinstance(emp_id, str):
            try:
                emp_id = UUID(emp_id)
            except ValueError:
                pass

        # Lock candidate's employee row to prevent race conditions with other workers
        # Uses standard blocking FOR UPDATE on PostgreSQL
        stmt = select(Employee).where(Employee.id == emp_id)
        if supports_lock:
            stmt = stmt.with_for_update()

        emp = db.execute(stmt).scalar_one_or_none()

        if emp is None:
            continue

        # Skip OOO employees (is_available == False)
        if not emp.is_available:
            logger.info("assigner_skip_ooo", employee_id=str(emp.id))
            continue

        # Skip self-assignment (email match)
        if emp.email.lower().strip() in norm_exclude_emails:
            logger.info("assigner_skip_self", employee_id=str(emp.id), email=emp.email)
            continue

        # Re-check live capacity inside the row lock
        active_count = count_active_assignments(emp.id, db)
        if active_count >= emp.capacity:
            logger.info("assigner_skip_capacity", employee_id=str(emp.id), active=active_count, capacity=emp.capacity)
            continue

        # Build reason string
        reason = build_reason_string(emp, task, candidate_score, active_count)

        # Create Assignment record
        assignment = Assignment(
            task_id=task.id,
            employee_id=emp.id,
            score=candidate_score["score"],
            score_breakdown=candidate_score["breakdown"],
            reason=reason,
            status=AssignmentStatus.ASSIGNED.value,
        )

        task.status = TaskStatus.ASSIGNED.value
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        logger.info(
            "task_assigned_successfully",
            task_id=str(task.id),
            employee_id=str(emp.id),
            score=candidate_score["score"],
        )
        return assignment

    # If all eligible candidates failed constraint/capacity checks under lock
    task.status = TaskStatus.UNASSIGNED_NO_ELIGIBLE.value
    db.commit()
    raise NoEligibleCandidateError(
        task.id, reason="All candidate slots were filled or locked by constraints."
    )
