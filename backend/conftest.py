"""
conftest.py — Shared pytest fixtures and configuration for the whole test suite.
"""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ── Pytest CLI options & markers ──────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live eval tests that call the real Groq API",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires --live flag and real GROQ_API_KEY")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip = pytest.mark.skip(reason="Pass --live to run live eval tests against real API")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)


# ── SQLite compatibility for PostgreSQL types in unit tests ───────────────────
import sqlite3
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles

sqlite3.register_adapter(list, lambda val: json.dumps(val))
sqlite3.register_adapter(dict, lambda val: json.dumps(val))

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


# ── Shared test constants ─────────────────────────────────────────────────────

SKILL_VOCAB = [
    "sql", "python", "powerbi", "data-analysis", "devops",
    "react", "java", "machine-learning", "testing", "infrastructure",
    "security", "reporting", "software-development",
]

CATEGORY_VOCAB = [
    "data-analysis", "software-development", "devops", "machine-learning",
    "reporting", "testing", "infrastructure", "security", "planning", "general",
]

RECEIVED_AT = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)
TIMEZONE_STR = "Asia/Kolkata"


# ── Groq mock helper ──────────────────────────────────────────────────────────

def make_groq_response(tasks: list[dict]) -> MagicMock:
    """
    Build a mock Groq API response that looks like a successful tool-call reply.
    Used in unit tests to avoid real API calls.
    """
    tool_call = MagicMock()
    tool_call.function.arguments = json.dumps({"tasks": tasks})

    message = MagicMock()
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def groq_response_factory():
    """Fixture that returns the make_groq_response helper."""
    return make_groq_response
