"""
tests/integration/test_full_pipeline.py — Integration tests for FastAPI endpoints & pipeline.
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_async_db
from app.main import app
from app.models.employee import Employee
from app.models.task import Task
from app.models.assignment import Assignment
from app.models.email import Email
from app.models.enums import TaskStatus
from worker.tasks import assign_task, process_email


# ── SQLite async test database fixture ────────────────────────────────────────

@pytest_asyncio.fixture
async def async_test_client():
    """Create test client connected to an in-memory SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestAsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with TestAsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_async_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, TestAsyncSessionLocal

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_check(async_test_client):
    client, _ = async_test_client
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ingest_authentication(async_test_client):
    client, _ = async_test_client
    payload = {
        "message_id": f"auth-test-{uuid4()}",
        "from": "user@example.com",
        "subject": "Test",
        "body": "Test body",
    }

    # Missing header -> 401
    resp_no_auth = await client.post("/ingest", json=payload)
    assert resp_no_auth.status_code == 401

    # Wrong header -> 401
    resp_bad_auth = await client.post("/ingest", json=payload, headers={"X-Webhook-Secret": "wrong"})
    assert resp_bad_auth.status_code == 401

    # Correct header -> 202
    resp_ok = await client.post(
        "/ingest",
        json=payload,
        headers={"X-Webhook-Secret": settings.WEBHOOK_SECRET},
    )
    assert resp_ok.status_code == 202
    data = resp_ok.json()
    assert "email_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_ingest_idempotency(async_test_client):
    client, _ = async_test_client
    msg_id = f"idempotent-{uuid4()}@company.com"
    payload = {
        "message_id": msg_id,
        "from": "manager@company.com",
        "subject": "Status Report",
        "body": "Please prepare the weekly status report.",
    }

    # First ingest
    r1 = await client.post(
        "/ingest",
        json=payload,
        headers={"X-Webhook-Secret": settings.WEBHOOK_SECRET},
    )
    assert r1.status_code == 202
    email_id_1 = r1.json()["email_id"]

    # Redelivered with same message_id
    r2 = await client.post(
        "/ingest",
        json=payload,
        headers={"X-Webhook-Secret": settings.WEBHOOK_SECRET},
    )
    assert r2.status_code == 202
    email_id_2 = r2.json()["email_id"]

    # Must return the same email_id
    assert email_id_1 == email_id_2


@pytest.mark.asyncio
async def test_employee_crud(async_test_client):
    client, _ = async_test_client

    # 1. Create employee
    create_payload = {
        "name": "Dev Test",
        "email": "dev.test@company.com",
        "role": "Software Developer",
        "seniority": "mid",
        "skills": ["python", "sql"],
        "capacity": 3,
        "is_available": True,
    }
    create_res = await client.post("/employees", json=create_payload)
    assert create_res.status_code == 201
    emp_data = create_res.json()
    emp_id = emp_data["id"]
    assert emp_data["name"] == "Dev Test"
    assert emp_data["active_tasks"] == 0

    # 2. Get list of employees
    list_res = await client.get("/employees")
    assert list_res.status_code == 200
    emps = list_res.json()
    assert any(e["id"] == emp_id for e in emps)

    # 3. Patch employee
    patch_payload = {"capacity": 5, "is_available": False}
    patch_res = await client.patch(f"/employees/{emp_id}", json=patch_payload)
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["capacity"] == 5
    assert updated["is_available"] is False


@pytest.mark.asyncio
async def test_email_polling_and_tasks_query(async_test_client):
    client, SessionLocal = async_test_client

    # Seed an email and two tasks directly in DB
    async with SessionLocal() as session:
        email = Email(
            message_id=f"poll-{uuid4()}@company.com",
            sender="mgr@company.com",
            subject="Analytics",
            body="Task 1 and Task 2",
            received_at=datetime.now(timezone.utc),
            status="processed",
        )
        session.add(email)
        await session.flush()

        t1 = Task(
            email_id=email.id,
            position=0,
            title="Task One",
            priority="high",
            required_skills=["python"],
            min_seniority="mid",
            status="extracted",
        )
        t2 = Task(
            email_id=email.id,
            position=1,
            title="Task Two",
            priority="medium",
            required_skills=["sql"],
            min_seniority="junior",
            status="extracted",
        )
        session.add_all([t1, t2])
        await session.commit()
        email_id = str(email.id)

    # Poll GET /emails/{id}
    res = await client.get(f"/emails/{email_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "processed"
    assert len(data["tasks"]) == 2
    assert data["tasks"][0]["title"] == "Task One"
    assert data["tasks"][1]["title"] == "Task Two"

    # Query GET /tasks?email_id=
    task_res = await client.get(f"/tasks?email_id={email_id}")
    assert task_res.status_code == 200
    tasks = task_res.json()
    assert len(tasks) == 2

