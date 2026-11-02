"""
app/routers/emails.py — Email query and polling endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.email import Email
from app.models.task import Task
from app.schemas.email import EmailDetailResponse, EmailTaskSummary

router = APIRouter(prefix="/emails", tags=["Emails"])


@router.get("/{id}", response_model=EmailDetailResponse, summary="Get email status and extracted tasks")
async def get_email(id: UUID, db: AsyncSession = Depends(get_async_db)):
    """
    Query email status and list all extracted tasks for polling.
    """
    stmt = select(Email).where(Email.id == id)
    email = (await db.execute(stmt)).scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Email {id} not found")

    tasks_stmt = select(Task).where(Task.email_id == id).order_by(Task.position)
    tasks = (await db.execute(tasks_stmt)).scalars().all()

    task_summaries = [
        EmailTaskSummary(
            id=t.id,
            position=t.position,
            title=t.title,
            status=t.status,
            priority=t.priority,
            confidence=t.llm_confidence,
        )
        for t in tasks
    ]

    return EmailDetailResponse(
        id=email.id,
        message_id=email.message_id,
        sender=email.sender,
        subject=email.subject,
        received_at=email.received_at,
        timezone=email.timezone,
        status=email.status,
        created_at=email.created_at,
        tasks=task_summaries,
    )

