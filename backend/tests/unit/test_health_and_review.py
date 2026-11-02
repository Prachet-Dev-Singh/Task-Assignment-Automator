"""
tests/unit/test_health_and_review.py — Unit tests for Phase 5 hardening features:
- Multi-component /health check
- Human-in-the-loop approval of review_required tasks
"""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_async_db
from app.main import app
from app.models.email import Email
from app.models.enums import TaskStatus
from app.models.task import Task


@pytest_asyncio.fixture
async def client_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestAsyncSession = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with TestAsyncSession() as session:
            yield session

    app.dependency_overrides[get_async_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, TestAsyncSession

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_check_returns_components(client_and_session):
    client, _ = client_and_session
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "components" in data
    assert "database" in data["components"]
    assert "redis" in data["components"]


@pytest.mark.asyncio
async def test_approve_review_required_task(client_and_session):
    client, SessionLocal = client_and_session

    async with SessionLocal() as session:
        email = Email(
            message_id=f"approve-{uuid4()}@co.com",
            sender="mgr@co.com",
            subject="Ambiguous Task",
            body="Vague request",
            received_at=datetime.now(timezone.utc),
        )
        session.add(email)
        await session.flush()

        task = Task(
            email_id=email.id,
            position=0,
            title="Needs Review",
            required_skills=[],
            min_seniority="mid",
            llm_confidence=0.45,
            status=TaskStatus.REVIEW_REQUIRED.value,
        )
        session.add(task)
        await session.commit()
        task_id = str(task.id)

    # Call approval endpoint with corrected skills and title
    approve_payload = {
        "title": "Confirmed PowerBI Dashboard Task",
        "required_skills": ["powerbi", "sql"],
        "min_seniority": "senior",
    }

    with patch("worker.tasks.assign_task.delay") as mock_delay:
        resp = await client.post(f"/tasks/{task_id}/approve", json=approve_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "extracted"
        assert data["title"] == "Confirmed PowerBI Dashboard Task"
        assert "powerbi" in data["required_skills"]
        assert data["min_seniority"] == "senior"
        mock_delay.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_cannot_approve_task_unless_review_required(client_and_session):
    client, SessionLocal = client_and_session

    async with SessionLocal() as session:
        email = Email(
            message_id=f"nonreview-{uuid4()}@co.com",
            sender="mgr@co.com",
            subject="Normal Task",
            body="Clear request",
            received_at=datetime.now(timezone.utc),
        )
        session.add(email)
        await session.flush()

        task = Task(
            email_id=email.id,
            position=0,
            title="Normal Task",
            status=TaskStatus.EXTRACTED.value,
        )
        session.add(task)
        await session.commit()
        task_id = str(task.id)

    # Calling approve on an already extracted task must fail with 400
    resp = await client.post(f"/tasks/{task_id}/approve", json={})
    assert resp.status_code == 400
    assert "only 'review_required' can be approved" in resp.json()["detail"]

