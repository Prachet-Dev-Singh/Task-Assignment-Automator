"""
tests/unit/test_extractor.py — Unit tests for services/extractor.py.

All tests mock the Groq client — no real API calls are made.
Five tests cover: clear task, multi-task, low confidence, unmapped skills, API failure.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import json
import pytest

from app.services.extractor import extract, ExtractionError

# Reuse shared constants from conftest
from conftest import SKILL_VOCAB, CATEGORY_VOCAB, RECEIVED_AT, TIMEZONE_STR, make_groq_response


# ── Test 1: Clear single task ─────────────────────────────────────────────────

@patch("app.services.extractor.Groq")
def test_clear_task_extraction(mock_groq_cls):
    """
    A clear, well-specified email produces exactly one validated task dict
    with correct fields and confidence >= 0.7.
    """
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_groq_response([
        {
            "task_title": "Prepare Q3 Analytics Report",
            "description": "Prepare the Q3 analytics report with regional breakdown by Friday.",
            "deadline": "2026-11-07T17:00:00Z",
            "priority": "high",
            "required_skills": ["sql", "powerbi", "data-analysis"],
            "unmapped_skills": [],
            "min_seniority": "mid",
            "category": "data-analysis",
            "confidence": 0.95,
        }
    ])

    results = extract("Prepare Q3 report by Friday 5pm.", RECEIVED_AT, TIMEZONE_STR, SKILL_VOCAB, CATEGORY_VOCAB)

    assert len(results) == 1
    task = results[0]
    assert task["task_title"] == "Prepare Q3 Analytics Report"
    assert task["priority"] == "high"
    assert "sql" in task["required_skills"]
    assert "powerbi" in task["required_skills"]
    assert task["deadline"] == "2026-11-07T17:00:00Z"
    assert task["confidence"] >= 0.7
    assert task["unmapped_skills"] == []


# ── Test 2: Multi-task email ───────────────────────────────────────────────────

@patch("app.services.extractor.Groq")
def test_multi_task_email_returns_two_tasks(mock_groq_cls):
    """
    An email describing two distinct tasks returns two separate task dicts.
    This validates that the array output contract works end-to-end.
    """
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_groq_response([
        {
            "task_title": "Build Q3 PowerBI Dashboard",
            "description": "Build the Q3 analytics dashboard in PowerBI.",
            "deadline": None,
            "priority": "high",
            "required_skills": ["powerbi", "data-analysis"],
            "unmapped_skills": [],
            "min_seniority": "mid",
            "category": "reporting",
            "confidence": 0.9,
        },
        {
            "task_title": "Update SQL Pipeline for New Region",
            "description": "Update the SQL data pipeline to include Southeast Asia region data.",
            "deadline": "2026-11-05T17:00:00Z",
            "priority": "medium",
            "required_skills": ["sql", "data-analysis"],
            "unmapped_skills": [],
            "min_seniority": "junior",
            "category": "data-analysis",
            "confidence": 0.88,
        },
    ])

    results = extract("Two tasks email body.", RECEIVED_AT, TIMEZONE_STR, SKILL_VOCAB, CATEGORY_VOCAB)

    assert len(results) == 2
    titles = {r["task_title"] for r in results}
    assert "Build Q3 PowerBI Dashboard" in titles
    assert "Update SQL Pipeline for New Region" in titles

    # Each task must have all required fields
    for task in results:
        for field in ["task_title", "description", "priority", "required_skills",
                      "unmapped_skills", "min_seniority", "category", "confidence"]:
            assert field in task


# ── Test 3: Low-confidence ambiguous email ────────────────────────────────────

@patch("app.services.extractor.Groq")
def test_ambiguous_email_produces_low_confidence(mock_groq_cls):
    """
    A vague, underspecified email results in confidence < 0.6,
    which will route the task to review_required in the worker.
    """
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_groq_response([
        {
            "task_title": "Handle Pending Issue",
            "description": "Something needs to be taken care of.",
            "deadline": None,
            "priority": "medium",
            "required_skills": [],
            "unmapped_skills": [],
            "min_seniority": "mid",
            "category": "general",
            "confidence": 0.32,
        }
    ])

    results = extract("Can someone handle this?", RECEIVED_AT, TIMEZONE_STR, SKILL_VOCAB, CATEGORY_VOCAB)

    assert len(results) == 1
    assert results[0]["confidence"] < 0.6


# ── Test 4: Skills outside vocabulary go into unmapped_skills ─────────────────

@patch("app.services.extractor.Groq")
def test_unmapped_skills_captured_not_discarded(mock_groq_cls):
    """
    When the task needs a skill not in the org vocabulary (e.g. 'salesforce'),
    it must appear in unmapped_skills and NOT in required_skills.
    This flags skill gaps rather than silently ignoring them.
    """
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_groq_response([
        {
            "task_title": "Integrate Salesforce CRM",
            "description": "Set up Salesforce CRM integration with the internal HR system.",
            "deadline": None,
            "priority": "medium",
            "required_skills": [],            # Salesforce NOT in vocab → goes to unmapped
            "unmapped_skills": ["salesforce", "crm"],
            "min_seniority": "senior",
            "category": "software-development",
            "confidence": 0.82,
        }
    ])

    results = extract("Need Salesforce CRM integration.", RECEIVED_AT, TIMEZONE_STR, SKILL_VOCAB, CATEGORY_VOCAB)

    assert len(results) == 1
    task = results[0]
    assert "salesforce" in task["unmapped_skills"]
    assert "crm" in task["unmapped_skills"]
    # Must NOT appear in required_skills — it's not in the vocabulary
    assert "salesforce" not in task["required_skills"]


# ── Test 5: API failure raises ExtractionError ────────────────────────────────

@patch("app.services.extractor.Groq")
def test_api_failure_raises_extraction_error(mock_groq_cls):
    """
    Any exception from the Groq client must be caught and re-raised as
    ExtractionError so the Celery worker can set status='extraction_failed'
    without letting a raw exception crash the worker process.
    """
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("Connection timeout")

    with pytest.raises(ExtractionError, match="Groq API call failed"):
        extract("Some email body.", RECEIVED_AT, TIMEZONE_STR, SKILL_VOCAB, CATEGORY_VOCAB)

