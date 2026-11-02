"""
app/main.py — FastAPI Application Entry Point.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.config import settings
from app.database import get_async_db
from app.logging_config import configure_logging
from app.routers import assignments, emails, employees, ingest, tasks

# Initialize structured logging
configure_logging()

app = FastAPI(
    title="Workplace Task Assignment System",
    description="AI-powered task assignment system: Ingestion -> LLM Extraction -> Candidate Scoring -> Assignment.",
    version="1.0.0",
)

# Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(ingest.router)
app.include_router(emails.router)
app.include_router(tasks.router)
app.include_router(employees.router)
app.include_router(assignments.router)


@app.get("/health", tags=["System"], summary="Comprehensive health check")
async def health_check(db: AsyncSession = Depends(get_async_db)):
    """
    Liveness and readiness check: verifies database and Redis connectivity.
    """
    components = {"database": "ok", "redis": "ok"}
    overall_status = "ok"

    # 1. Database check
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        components["database"] = f"down: {exc}"
        overall_status = "degraded"

    # 2. Redis check
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1.0)
        await r.ping()
        await r.aclose()
    except Exception as exc:
        components["redis"] = f"down: {exc}"
        overall_status = "degraded"

    return {
        "status": overall_status,
        "components": components,
    }

