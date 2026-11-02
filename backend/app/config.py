"""
app/config.py — All configuration loaded from .env via Pydantic BaseSettings.
Validation fails at startup if required keys are missing.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    # Two URLs: asyncpg for FastAPI, psycopg2 for Celery worker + Alembic
    DATABASE_URL: str          # postgresql+asyncpg://...
    DATABASE_SYNC_URL: str     # postgresql+psycopg2://...

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Groq LLM API (free tier) ─────────────────────────────────────────────
    GROQ_API_KEY: str
    LLM_MODEL: str = "llama-3.3-70b-versatile"

    # ── Org defaults ──────────────────────────────────────────────────────────
    # Fallback timezone when no per-email timezone is provided in the ingest payload
    ORG_TIMEZONE: str = "UTC"

    # ── Security ──────────────────────────────────────────────────────────────
    WEBHOOK_SECRET: str

    # ── Pipeline tuning ───────────────────────────────────────────────────────
    LLM_CONFIDENCE_THRESHOLD: float = 0.60
    DEFAULT_EMPLOYEE_CAPACITY: int = 3
    URGENCY_DEADLINE_HOURS: int = 24

    # ── Scoring weights — normal tasks ────────────────────────────────────────
    SCORING_WEIGHTS_SKILLS: float = 0.40
    SCORING_WEIGHTS_AVAILABILITY: float = 0.30
    SCORING_WEIGHTS_PERFORMANCE: float = 0.20
    SCORING_WEIGHTS_SENIORITY: float = 0.10

    # ── Scoring weights — urgent tasks (deadline < URGENCY_DEADLINE_HOURS) ───
    URGENCY_WEIGHTS_SKILLS: float = 0.30
    URGENCY_WEIGHTS_AVAILABILITY: float = 0.45
    URGENCY_WEIGHTS_PERFORMANCE: float = 0.15
    URGENCY_WEIGHTS_SENIORITY: float = 0.10

    # ── Auto-rating ───────────────────────────────────────────────────────────
    AUTO_RATING_ON_TIME: float = 4.0
    AUTO_RATING_LATE: float = 2.0

    # ── Canonical category vocabulary — seeded here so it's never empty ───────
    # Worker unions this with categories observed in task_history + tasks tables.
    # All values must be lowercase and hyphenated.
    CATEGORY_VOCAB_SEED: list[str] = [
        "data-analysis",
        "software-development",
        "devops",
        "machine-learning",
        "design",
        "documentation",
        "testing",
        "deployment",
        "research",
        "infrastructure",
        "security",
        "reporting",
        "support",
        "planning",
        "general",
    ]


settings = Settings()
