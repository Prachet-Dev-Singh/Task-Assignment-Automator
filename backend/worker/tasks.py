"""
worker/tasks.py — Celery background tasks chaining Stages 2 -> 3 -> 4.

Two tasks:
  - process_email: runs Stage 2 (LLM extraction), saves Task rows,
    commits, then enqueues assign_task for each extracted task.
  - assign_task: runs Stage 3 (scoring) and Stage 4 (assignment).
    Can be called standalone or on task reassignment without re-running the LLM.
"""

import logging
from typing import Sequence
from uuid import UUID

from celery import Task as CeleryTask
from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.email import Email
from app.models.employee import Employee
from app.models.enums import EmailStatus, TaskStatus
from app.models.task import Task
from app.models.task_history import TaskHistory
from app.services import assigner, extractor, scorer
from app.services.assigner import count_active_assignments
from app.services.scorer import _normalize_skill_list
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_skill_vocabulary(db) -> list[str]:
    """Retrieve canonical skill vocabulary from all employees."""
    employees = db.execute(select(Employee)).scalars().all()
    skills_set = set()
    for emp in employees:
        for s in _normalize_skill_list(emp.skills):
            skills_set.add(s)
    return sorted(list(skills_set))


def _get_category_vocabulary(db) -> list[str]:
    """Retrieve canonical category vocabulary from config seed + DB."""
    cats = {c.lower().strip() for c in settings.CATEGORY_VOCAB_SEED}
    db_cats = db.execute(
        select(Task.category).where(Task.category.is_not(None))
    ).scalars().all()
    for c in db_cats:
        if c:
            cats.add(str(c).lower().strip())
    return sorted(list(cats))


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="worker.tasks.process_email")
def process_email(self: CeleryTask, email_id: str):
    """
    Stage 2: LLM Extraction.
    Extracts structured tasks from email body and persists them.
    Commits first, then enqueues assign_task for eligible tasks.
    """
    db = SyncSessionLocal()
    try:
        e_uuid = UUID(email_id) if isinstance(email_id, str) else email_id
        email = db.get(Email, e_uuid)
        if not email:
            logger.error("email_not_found", email_id=str(email_id))
            return

        email.status = EmailStatus.PROCESSING.value
        db.commit()

        # Build vocabulary dynamically
        skill_vocab = _get_skill_vocabulary(db)
        category_vocab = _get_category_vocabulary(db)

        # Stage 2: Call extractor
        try:
            extracted_tasks = extractor.extract(
                body=email.body,
                received_at=email.received_at,
                timezone_str=email.timezone or settings.ORG_TIMEZONE,
                skill_vocab=skill_vocab,
                category_vocab=category_vocab,
            )
        except Exception as exc:
            logger.exception("extraction_failed", email_id=str(email_id), error=str(exc))
            email.status = EmailStatus.FAILED.value
            db.commit()
            raise self.retry(exc=exc)

        # Persist extracted tasks
        created_tasks: list[Task] = []
        for i, t_data in enumerate(extracted_tasks):
            # Check confidence gate
            conf = t_data.get("confidence", 1.0)
            status_val = (
                TaskStatus.REVIEW_REQUIRED.value
                if conf < settings.LLM_CONFIDENCE_THRESHOLD
                else TaskStatus.EXTRACTED.value
            )

            deadline_val = None
            if t_data.get("deadline"):
                from datetime import datetime
                try:
                    deadline_val = datetime.fromisoformat(t_data["deadline"].replace("Z", "+00:00"))
                except Exception:
                    deadline_val = None

            task_obj = Task(
                email_id=email.id,
                position=i,
                title=t_data["task_title"],
                description=t_data.get("description"),
                deadline=deadline_val,
                priority=t_data.get("priority", "medium"),
                required_skills=t_data.get("required_skills", []),
                unmapped_skills=t_data.get("unmapped_skills", []),
                min_seniority=t_data.get("min_seniority", "mid"),
                category=t_data.get("category", "general"),
                llm_confidence=conf,
                status=status_val,
            )
            db.add(task_obj)
            created_tasks.append(task_obj)

        email.status = EmailStatus.PROCESSED.value
        # Commit tasks to DB first before enqueueing background assignment
        db.commit()

        # Enqueue assignment for all extracted tasks meeting confidence threshold
        for task in created_tasks:
            if task.status == TaskStatus.EXTRACTED.value:
                assign_task.delay(str(task.id))

        logger.info("email_processed_successfully", email_id=str(email_id), task_count=len(created_tasks))

    except Exception as exc:
        db.rollback()
        logger.exception("process_email_error", email_id=str(email_id), error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="worker.tasks.assign_task")
def assign_task(self: CeleryTask, task_id: str, exclude_employee_ids: list[str] | None = None):
    """
    Stages 3 & 4: Candidate Scoring & Assignment.
    Scores all available employees and records the winning assignment.
    """
    db = SyncSessionLocal()
    try:
        t_uuid = UUID(task_id) if isinstance(task_id, str) else task_id
        task = db.get(Task, t_uuid)
        if not task:
            logger.error("task_not_found", task_id=str(task_id))
            return

        email = db.get(Email, task.email_id)
        sender_email = email.sender if email else None

        # Fetch available candidates
        employees = db.execute(
            select(Employee).where(Employee.is_available.is_(True))
        ).scalars().all()

        if not employees:
            task.status = TaskStatus.UNASSIGNED_NO_ELIGIBLE.value
            db.commit()
            return

        # Stage 3: Score candidates
        scored_candidates = []
        for emp in employees:
            active_count = count_active_assignments(emp.id, db)
            history = db.execute(
                select(TaskHistory).where(TaskHistory.employee_id == emp.id)
            ).scalars().all()

            s = scorer.score_candidate(
                task_required_skills=task.required_skills,
                task_min_seniority=task.min_seniority,
                task_category=task.category,
                task_deadline=task.deadline,
                emp_id=emp.id,
                emp_skills=emp.skills,
                emp_seniority=emp.seniority,
                emp_capacity=emp.capacity,
                emp_active_count=active_count,
                history_records=history,
            )
            scored_candidates.append(s)

        # Stage 4: Assign best-fit
        exclude_emails = [sender_email] if sender_email else []
        try:
            assignment = assigner.assign(
                task=task,
                scored_candidates=scored_candidates,
                db=db,
                exclude_emails=exclude_emails,
                exclude_employee_ids=exclude_employee_ids,
            )
            logger.info("assign_task_success", task_id=str(task_id), assignment_id=str(assignment.id))
        except assigner.NoEligibleCandidateError as e:
            logger.warning("assign_task_no_eligible", task_id=str(task_id), reason=str(e))

    except Exception as exc:
        db.rollback()
        logger.exception("assign_task_error", task_id=str(task_id), error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()

