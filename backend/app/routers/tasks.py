"""
app/routers/tasks.py — Task query and update endpoints.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.assignment import Assignment
from app.models.enums import VALID_TRANSITIONS, TaskStatus
from app.models.task import Task
from app.schemas.task import (
    TaskApproveRequest,
    TaskDetailResponse,
    TaskRateRequest,
    TaskResponse,
    TaskStatusUpdateRequest,
)
from app.services import tracker
from app.services.scorer import _normalize_skill_list
from worker.tasks import assign_task

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=list[TaskResponse], summary="List tasks with filters")
async def list_tasks(
    email_id: Optional[UUID] = Query(None, description="Filter by originating email ID"),
    status: Optional[str] = Query(None, description="Filter by task status"),
    priority: Optional[str] = Query(None, description="Filter by task priority"),
    db: AsyncSession = Depends(get_async_db),
):
    """List tasks, optionally filtered by email_id, status, or priority."""
    stmt = select(Task)
    if email_id:
        stmt = stmt.where(Task.email_id == email_id)
    if status:
        stmt = stmt.where(Task.status == status.lower().strip())
    if priority:
        stmt = stmt.where(Task.priority == priority.lower().strip())

    stmt = stmt.order_by(Task.created_at.desc())
    tasks = (await db.execute(stmt)).scalars().all()

    # Normalize skills for response serialization
    results = []
    for t in tasks:
        t_dict = {
            "id": t.id,
            "email_id": t.email_id,
            "position": t.position,
            "title": t.title,
            "description": t.description,
            "deadline": t.deadline,
            "priority": t.priority,
            "required_skills": _normalize_skill_list(t.required_skills),
            "unmapped_skills": _normalize_skill_list(t.unmapped_skills),
            "min_seniority": t.min_seniority,
            "category": t.category,
            "llm_confidence": t.llm_confidence,
            "status": t.status,
            "created_at": t.created_at,
        }
        results.append(TaskResponse(**t_dict))
    return results


@router.get("/{id}", response_model=TaskDetailResponse, summary="Get single task with assignment")
async def get_task(id: UUID, db: AsyncSession = Depends(get_async_db)):
    """Retrieve full task details including active assignment and score breakdown."""
    stmt = select(Task).where(Task.id == id)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {id} not found")

    # Fetch assignment
    assign_stmt = select(Assignment).where(Assignment.task_id == id).order_by(Assignment.assigned_at.desc())
    assignment = (await db.execute(assign_stmt)).scalars().first()

    assign_dict = None
    if assignment:
        assign_dict = {
            "id": assignment.id,
            "employee_id": assignment.employee_id,
            "score": assignment.score,
            "score_breakdown": assignment.score_breakdown,
            "reason": assignment.reason,
            "status": assignment.status,
            "assigned_at": assignment.assigned_at,
            "completed_at": assignment.completed_at,
            "rating": assignment.rating,
        }

    return TaskDetailResponse(
        id=task.id,
        email_id=task.email_id,
        position=task.position,
        title=task.title,
        description=task.description,
        deadline=task.deadline,
        priority=task.priority,
        required_skills=_normalize_skill_list(task.required_skills),
        unmapped_skills=_normalize_skill_list(task.unmapped_skills),
        min_seniority=task.min_seniority,
        category=task.category,
        llm_confidence=task.llm_confidence,
        status=task.status,
        created_at=task.created_at,
        assignment=assign_dict,
    )


@router.patch("/{id}/status", response_model=TaskResponse, summary="Update task status")
async def update_task_status_endpoint(
    id: UUID,
    payload: TaskStatusUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Update task lifecycle status using the tracker service.
    Validates state transitions against the VALID_TRANSITIONS state machine.
    """
    stmt = select(Task).where(Task.id == id)
    task_exists = (await db.execute(stmt)).scalar_one_or_none()
    if not task_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {id} not found")

    try:
        updated_task, _ = await db.run_sync(
            lambda sync_session: tracker.update_task_status(id, payload.status, sync_session)
        )
    except tracker.InvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return TaskResponse(
        id=updated_task.id,
        email_id=updated_task.email_id,
        position=updated_task.position,
        title=updated_task.title,
        description=updated_task.description,
        deadline=updated_task.deadline,
        priority=updated_task.priority,
        required_skills=_normalize_skill_list(updated_task.required_skills),
        unmapped_skills=_normalize_skill_list(updated_task.unmapped_skills),
        min_seniority=updated_task.min_seniority,
        category=updated_task.category,
        llm_confidence=updated_task.llm_confidence,
        status=updated_task.status,
        created_at=updated_task.created_at,
    )


@router.post("/{id}/approve", response_model=TaskResponse, summary="Approve low-confidence review_required task")
async def approve_task_for_assignment(
    id: UUID,
    payload: Optional[TaskApproveRequest] = None,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Human-in-the-loop approval endpoint for tasks marked 'review_required'.
    Transitions status to 'extracted' and enqueues background assignment.
    """
    stmt = select(Task).where(Task.id == id)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {id} not found")

    if task.status != TaskStatus.REVIEW_REQUIRED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task is in status '{task.status}', only '{TaskStatus.REVIEW_REQUIRED.value}' can be approved.",
        )

    if payload:
        if payload.title:
            task.title = payload.title.strip()
        if payload.required_skills is not None:
            task.required_skills = [s.lower().strip() for s in payload.required_skills]
        if payload.min_seniority:
            task.min_seniority = payload.min_seniority.lower().strip()

    task.status = TaskStatus.EXTRACTED.value
    await db.commit()
    await db.refresh(task)

    # Enqueue assignment worker
    try:
        assign_task.delay(str(task.id))
    except Exception:
        pass

    return TaskResponse(
        id=task.id,
        email_id=task.email_id,
        position=task.position,
        title=task.title,
        description=task.description,
        deadline=task.deadline,
        priority=task.priority,
        required_skills=_normalize_skill_list(task.required_skills),
        unmapped_skills=_normalize_skill_list(task.unmapped_skills),
        min_seniority=task.min_seniority,
        category=task.category,
        llm_confidence=task.llm_confidence,
        status=task.status,
        created_at=task.created_at,
    )


@router.post("/{id}/rate", summary="Submit manual 1-5 rating for completed task")
async def rate_completed_task(
    id: UUID,
    payload: TaskRateRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Submit a manual 1.0 - 5.0 performance rating for a completed task.
    Updates the assignment record and feeds into future scoring calculations.
    """
    try:
        assignment, history = await db.run_sync(
            lambda sync_session: tracker.record_manual_rating(id, payload.rating, sync_session)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "task_id": str(id),
        "assignment_id": str(assignment.id),
        "employee_id": str(assignment.employee_id),
        "rating": assignment.rating,
        "message": "Performance rating recorded successfully.",
    }

