"""
app/routers/employees.py — Employee management endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.assignment import Assignment
from app.models.employee import Employee
from app.models.enums import ACTIVE_TASK_STATUSES
from app.schemas.employee import EmployeeCreate, EmployeeResponse, EmployeeUpdate
from app.services.scorer import _normalize_skill_list

router = APIRouter(prefix="/employees", tags=["Employees"])


async def _get_active_task_count(employee_id: UUID, db: AsyncSession) -> int:
    stmt = (
        select(func.count(Assignment.id))
        .where(Assignment.employee_id == employee_id)
        .where(Assignment.status.in_([s.value for s in ACTIVE_TASK_STATUSES]))
    )
    return (await db.execute(stmt)).scalar() or 0


@router.get("", response_model=list[EmployeeResponse], summary="List all employees with live workload")
async def list_employees(db: AsyncSession = Depends(get_async_db)):
    """List employees with live count of currently assigned / in_progress tasks."""
    stmt = select(Employee).order_by(Employee.name)
    employees = (await db.execute(stmt)).scalars().all()

    results = []
    for emp in employees:
        active = await _get_active_task_count(emp.id, db)
        results.append(
            EmployeeResponse(
                id=emp.id,
                name=emp.name,
                email=emp.email,
                role=emp.role,
                seniority=emp.seniority,
                skills=_normalize_skill_list(emp.skills),
                capacity=emp.capacity,
                is_available=emp.is_available,
                active_tasks=active,
                created_at=emp.created_at,
            )
        )
    return results


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED, summary="Create an employee")
async def create_employee(payload: EmployeeCreate, db: AsyncSession = Depends(get_async_db)):
    """Add a new employee to the directory."""
    check_stmt = select(Employee).where(Employee.email == payload.email.lower().strip())
    existing = (await db.execute(check_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee with this email already exists")

    emp = Employee(
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        role=payload.role.strip(),
        seniority=payload.seniority.lower().strip(),
        skills=[s.lower().strip() for s in payload.skills],
        capacity=payload.capacity,
        is_available=payload.is_available,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)

    return EmployeeResponse(
        id=emp.id,
        name=emp.name,
        email=emp.email,
        role=emp.role,
        seniority=emp.seniority,
        skills=_normalize_skill_list(emp.skills),
        capacity=emp.capacity,
        is_available=emp.is_available,
        active_tasks=0,
        created_at=emp.created_at,
    )


@router.patch("/{id}", response_model=EmployeeResponse, summary="Update employee profile")
async def update_employee(
    id: UUID,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """Update employee skills, capacity, or availability (e.g. OOO flag)."""
    stmt = select(Employee).where(Employee.id == id)
    emp = (await db.execute(stmt)).scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Employee {id} not found")

    if payload.name is not None:
        emp.name = payload.name.strip()
    if payload.role is not None:
        emp.role = payload.role.strip()
    if payload.seniority is not None:
        emp.seniority = payload.seniority.lower().strip()
    if payload.skills is not None:
        emp.skills = [s.lower().strip() for s in payload.skills]
    if payload.capacity is not None:
        emp.capacity = payload.capacity
    if payload.is_available is not None:
        emp.is_available = payload.is_available

    await db.commit()
    await db.refresh(emp)
    active = await _get_active_task_count(emp.id, db)

    return EmployeeResponse(
        id=emp.id,
        name=emp.name,
        email=emp.email,
        role=emp.role,
        seniority=emp.seniority,
        skills=_normalize_skill_list(emp.skills),
        capacity=emp.capacity,
        is_available=emp.is_available,
        active_tasks=active,
        created_at=emp.created_at,
    )

