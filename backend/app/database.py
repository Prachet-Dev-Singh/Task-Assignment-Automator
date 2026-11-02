"""
app/database.py — Two SQLAlchemy engines.

  async_engine      → FastAPI async routes and services
  sync_engine       → Celery worker tasks and Alembic migrations

Never mix them: asyncpg is incompatible with synchronous Celery code,
and psycopg2 cannot be used in an async context.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


# ── Shared declarative base ───────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Async engine — FastAPI ────────────────────────────────────────────────────
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_db():
    """FastAPI dependency — yields an async session and closes it after the request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ── Sync engine — Celery worker + Alembic ────────────────────────────────────
sync_engine = create_engine(
    settings.DATABASE_SYNC_URL,
    pool_pre_ping=True,
    echo=False,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)


def get_sync_db():
    """
    Celery / script dependency — yields a sync session.
    Usage in worker:
        db = next(get_sync_db())
        try:
            ...
        finally:
            db.close()
    """
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
