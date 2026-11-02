"""
app/routers/assignments.py — Assignment query endpoints.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.assignment import Assignment
from app.models.employee import Employee
from app.models.task import Task
from app.schemas.assignment import AssigneeSummary, AssignmentResponse, TaskSummary
from app.services.scorer import _normalize_skill_list

router = APIRouter(prefix="/assignments", tags=["Assignments"])


@router.get("", response_model=list[AssignmentResponse], summary="List assignments with filters")
async def list_assignments(
    task_id: Optional[UUID] = Query(None, description="Filter by task ID"),
    employee_id: Optional[UUID] = Query(None, description="Filter by employee ID"),
    status: Optional[str] = Query(None, description="Filter by assignment status"),
    date_from: Optional[datetime] = Query(None, description="Filter assigned after this timestamp"),
    date_to: Optional[datetime] = Query(None, description="Filter assigned before this timestamp"),
    db: AsyncSession = Depends(get_async_db),
):
    """Query assignments matching criteria."""
    stmt = select(Assignment)
    if task_id:
        stmt = stmt.where(Assignment.task_id == task_id)
    if employee_id:
        stmt = stmt.where(Assignment.employee_id == employee_id)
    if status:
        stmt = stmt.where(Assignment.status == status.lower().strip())
    if date_from:
        stmt = stmt.where(Assignment.assigned_at >= date_from)
    if date_to:
        stmt = stmt.where(Assignment.assigned_at <= date_to)

    stmt = stmt.order_by(Assignment.assigned_at.desc())
    assignments = (await db.execute(stmt)).scalars().all()

    results = []
    for a in assignments:
        # Load task and employee summaries
        t_stmt = select(Task).where(Task.id == a.task_id)
        task = (await db.execute(t_stmt)).scalar_one_or_none()

        e_stmt = select(Employee).where(Employee.id == a.employee_id)
        emp = (await db.execute(e_stmt)).scalar_one_or_none()

        task_summary = None
        if task:
            task_summary = TaskSummary(
                id=task.id,
                title=task.title,
                priority=task.priority,
                deadline=task.deadline,
                required_skills=_normalize_skill_list(task.required_skills),
            )

        emp_summary = None
        if emp:
            emp_summary = AssigneeSummary(
                id=emp.id,
                name=emp.name,
                email=emp.email,
                role=emp.role,
                seniority=emp.seniority,
            )

        results.append(
            AssignmentResponse(
                id=a.id,
                task_id=a.task_id,
                employee_id=a.employee_id,
                score=a.score,
                score_breakdown=a.score_breakdown,
                reason=a.reason,
                status=a.status,
                assigned_at=a.assigned_at,
                completed_at=a.completed_at,
                rating=a.rating,
                task=task_summary,
                assignee=emp_summary,
            )
        )
    return results


@router.get("/{id}", response_model=AssignmentResponse, summary="Get full assignment record")
async def get_assignment(id: UUID, db: AsyncSession = Depends(get_async_db)):
    """Retrieve complete assignment details with full score breakdown JSON."""
    stmt = select(Assignment).where(Assignment.id == id)
    assignment = (await db.execute(stmt)).scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Assignment {id} not found")

    t_stmt = select(Task).where(Task.id == assignment.task_id)
    task = (await db.execute(t_stmt)).scalar_one_or_none()

    e_stmt = select(Employee).where(Employee.id == assignment.employee_id)
    emp = (await db.execute(e_stmt)).scalar_one_or_none()

    task_summary = None
    if task:
        task_summary = TaskSummary(
            id=task.id,
            title=task.title,
            priority=task.priority,
            deadline=task.deadline,
            required_skills=_normalize_skill_list(task.required_skills),
        )

    emp_summary = None
    if emp:
        emp_summary = AssigneeSummary(
            id=emp.id,
            name=emp.name,
            email=emp.email,
            role=emp.role,
            seniority=emp.seniority,
        )

    return AssignmentResponse(
        id=assignment.id,
        task_id=assignment.task_id,
        employee_id=assignment.employee_id,
        score=assignment.score,
        score_breakdown=assignment.score_breakdown,
        reason=assignment.reason,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        completed_at=assignment.completed_at,
        rating=assignment.rating,
        task=task_summary,
        assignee=emp_summary,
    )

