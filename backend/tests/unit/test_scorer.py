"""
tests/unit/test_scorer.py — Unit tests for candidate scoring engine.

Tests all 4 signals in isolation, coverage vs Jaccard, urgency weight shifting,
and hard disqualify rules.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import settings
from app.services.scorer import score_candidate


def test_coverage_does_not_penalise_broad_skills():
    """
    Coverage formula: |T ∩ E| / |T|.
    A candidate with 8 skills against a 2-skill task covers 100% of the task's skills,
    so skills_score should be 1.0 (unlike Jaccard which would score 2/8 = 0.25).
    """
    task_skills = ["python", "sql"]
    emp_skills = ["python", "sql", "react", "java", "devops", "aws", "docker", "testing"]

    result = score_candidate(
        task_required_skills=task_skills,
        task_min_seniority="mid",
        task_category="data-analysis",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=emp_skills,
        emp_seniority="mid",
        emp_capacity=3,
        emp_active_count=0,
    )

    assert result["breakdown"]["skills"] == 1.0


def test_partial_skill_coverage():
    """If candidate has 1 out of 2 required skills, skills_score is exactly 0.5."""
    task_skills = ["python", "sql"]
    emp_skills = ["python", "react"]

    result = score_candidate(
        task_required_skills=task_skills,
        task_min_seniority="mid",
        task_category="software-development",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=emp_skills,
        emp_seniority="mid",
        emp_capacity=3,
        emp_active_count=0,
    )

    assert result["breakdown"]["skills"] == 0.5


def test_empty_required_skills_scores_full():
    """Tasks with no skill requirements give full 1.0 skills score to everyone."""
    result = score_candidate(
        task_required_skills=[],
        task_min_seniority="junior",
        task_category="general",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=["python"],
        emp_seniority="junior",
        emp_capacity=3,
        emp_active_count=0,
    )

    assert result["breakdown"]["skills"] == 1.0


def test_at_capacity_hard_disqualifies():
    """Employee at full capacity gets avail_score = 0.0 and final score = 0.0."""
    result = score_candidate(
        task_required_skills=["python"],
        task_min_seniority="junior",
        task_category="general",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=["python"],
        emp_seniority="mid",
        emp_capacity=3,
        emp_active_count=3,  # 3 of 3 used
    )

    assert result["breakdown"]["availability"] == 0.0
    assert result["score"] == 0.0  # Hard disqualify


def test_past_performance_recency_weighting():
    """Recency weighting: newer tasks have weight 1.0, 0.9, 0.81..."""
    history = [
        {"category": "data-analysis", "rating": 5.0},  # newest (i=0): 5.0 * 1.0
        {"category": "data-analysis", "rating": 3.0},  # older (i=1):  3.0 * 0.9
        {"category": "devops", "rating": 1.0},         # different category: ignored
    ]

    result = score_candidate(
        task_required_skills=["sql"],
        task_min_seniority="mid",
        task_category="data-analysis",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=["sql"],
        emp_seniority="mid",
        emp_capacity=3,
        emp_active_count=0,
        history_records=history,
    )

    expected_perf = ((5.0 / 5.0) * 1.0 + (3.0 / 5.0) * 0.9) / (1.0 + 0.9)
    assert abs(result["breakdown"]["performance"] - round(expected_perf, 4)) < 0.001


def test_past_performance_neutral_when_no_history():
    """When candidate has no history in this category, performance score is neutral 0.5."""
    result = score_candidate(
        task_required_skills=["sql"],
        task_min_seniority="mid",
        task_category="machine-learning",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=["sql"],
        emp_seniority="mid",
        emp_capacity=3,
        emp_active_count=0,
        history_records=[],
    )

    assert result["breakdown"]["performance"] == 0.5


def test_seniority_floor_disqualifies_underqualified():
    """Junior candidate for a Senior task (gap = -2) gets seniority = 0.0 and score = 0.0."""
    result = score_candidate(
        task_required_skills=["python"],
        task_min_seniority="senior",
        task_category="devops",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=["python"],
        emp_seniority="junior",  # 2 levels below senior
        emp_capacity=3,
        emp_active_count=0,
    )

    assert result["breakdown"]["seniority"] == 0.0
    assert result["score"] == 0.0  # Hard disqualify


def test_seniority_one_level_below_gives_half_credit():
    """Mid candidate for a Senior task (gap = -1) gets seniority_score = 0.5."""
    result = score_candidate(
        task_required_skills=["python"],
        task_min_seniority="senior",
        task_category="devops",
        task_deadline=None,
        emp_id=uuid4(),
        emp_skills=["python"],
        emp_seniority="mid",  # 1 level below
        emp_capacity=3,
        emp_active_count=0,
    )

    assert result["breakdown"]["seniority"] == 0.5
    assert result["score"] > 0.0


def test_urgency_shifts_weights_toward_availability():
    """
    When deadline is in 4 hours (< 24h), is_urgent_applied is True,
    and availability weight is boosted to 0.45.
    """
    urgent_deadline = datetime.now(timezone.utc) + timedelta(hours=4)

    result = score_candidate(
        task_required_skills=["python"],
        task_min_seniority="mid",
        task_category="devops",
        task_deadline=urgent_deadline,
        emp_id=uuid4(),
        emp_skills=["python"],
        emp_seniority="mid",
        emp_capacity=4,
        emp_active_count=1,  # 3 of 4 free -> avail = 0.75
    )

    assert result["is_urgent_applied"] is True

    # Check calculated score matches urgency weights
    expected = (
        settings.URGENCY_WEIGHTS_SKILLS * 1.0
        + settings.URGENCY_WEIGHTS_AVAILABILITY * 0.75
        + settings.URGENCY_WEIGHTS_PERFORMANCE * 0.5
        + settings.URGENCY_WEIGHTS_SENIORITY * 1.0
    )
    assert abs(result["score"] - round(expected, 4)) < 0.001

