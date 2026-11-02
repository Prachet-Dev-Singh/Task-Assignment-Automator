"""
app/services/scorer.py — Stage 3: Candidate Scoring Engine.

Called once per (task, employee) pair. Pure computation.

Design decisions:
  - Skills match uses COVERAGE: |T ∩ E| / |T|. A senior with broad skills is NOT
    penalised for having skills beyond what the task requires (unlike Jaccard).
    If task has no required skills, all candidates score 1.0 equally.
  - Availability linearly penalises load: 1.0 - (active_count / capacity).
    active_count includes both ASSIGNED and IN_PROGRESS assignments.
    At or over capacity -> avail_score = 0.0 (hard disqualify).
  - Past performance: recency-weighted average of ratings on matching category.
    Weights decay as 0.9^i for past tasks. If no history in category, neutral 0.5.
  - Seniority fit:
      gap >= 0  (meets or exceeds): 1.0
      gap == -1 (one level below):  0.5
      gap < -1  (two+ below):       0.0 (hard disqualify, e.g. junior for senior task)
  - Urgency weight shift:
      If deadline is within URGENCY_DEADLINE_HOURS, weights shift dynamically
      toward availability (45%) to favour the candidate with immediate capacity.
  - Hard disqualify:
      If availability == 0.0 or seniority == 0.0 -> overall score = 0.0.
"""

from datetime import datetime, timezone
from typing import Any, Sequence

from app.config import settings

SENIORITY_LEVELS: list[str] = ["junior", "mid", "senior", "lead"]


def compute_hours_until(deadline: datetime | str | None) -> float | None:
    """Compute hours remaining until deadline relative to now (UTC)."""
    if not deadline:
        return None
    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        except ValueError:
            return None

    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    diff = (deadline - now).total_seconds() / 3600.0
    return diff


def _normalize_skill_list(skills_val: Any) -> list[str]:
    """Ensure skills are a flat list of strings across SQLite and PostgreSQL."""
    if not skills_val:
        return []
    import json
    if isinstance(skills_val, (list, tuple)) and len(skills_val) > 0 and skills_val[0] == "[":
        try:
            skills_val = json.loads("".join(str(c) for c in skills_val))
        except Exception:
            pass
    elif isinstance(skills_val, str):
        try:
            skills_val = json.loads(skills_val)
        except Exception:
            return [skills_val.lower().strip()]
    return [str(s).lower().strip() for s in (skills_val or [])]


def score_candidate(
    task_required_skills: Sequence[str],
    task_min_seniority: str,
    task_category: str | None,
    task_deadline: datetime | str | None,
    emp_id: str | Any,
    emp_skills: Sequence[str],
    emp_seniority: str,
    emp_capacity: int,
    emp_active_count: int,
    history_records: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """
    Score a single employee candidate against a task.

    Args:
        task_required_skills: Required skill tags (lowercase).
        task_min_seniority:   Minimum required seniority ('junior'|'mid'|'senior'|'lead').
        task_category:        Category tag of the task (e.g. 'data-analysis').
        task_deadline:        Task deadline datetime or ISO string.
        emp_id:               Employee UUID or string id.
        emp_skills:           Employee skill tags (lowercase).
        emp_seniority:        Employee seniority level.
        emp_capacity:         Max concurrent tasks for employee.
        emp_active_count:     Currently active tasks (assigned + in_progress).
        history_records:      List of objects/dicts with 'category' and 'rating' (1-5).

    Returns:
        Dict containing employee_id, final score (0.0 - 1.0), and per-signal breakdown.
    """
    # ── Signal 1: Skills Coverage ─────────────────────────────────────────────
    # |T ∩ E| / |T|
    req_skills_clean = _normalize_skill_list(task_required_skills)
    emp_skills_clean = _normalize_skill_list(emp_skills)

    req_set = set(req_skills_clean)
    emp_set = set(emp_skills_clean)

    if not req_set:
        skills_score = 1.0
    else:
        matched = req_set & emp_set
        skills_score = len(matched) / len(req_set)

    # ── Signal 2: Availability ────────────────────────────────────────────────
    # Linear drop based on load. 0 slots remaining -> 0.0
    capacity = max(1, emp_capacity)
    if emp_active_count >= capacity:
        avail_score = 0.0
    else:
        avail_score = max(0.0, 1.0 - (emp_active_count / capacity))

    # ── Signal 3: Past Performance ────────────────────────────────────────────
    # Recency-weighted average for tasks in the same category
    same_cat_ratings: list[float] = []
    if history_records and task_category:
        norm_task_cat = task_category.lower().strip()
        for h in history_records:
            h_cat = getattr(h, "category", None) or (h.get("category") if isinstance(h, dict) else None)
            h_rating = getattr(h, "rating", None) or (h.get("rating") if isinstance(h, dict) else None)
            if h_cat and str(h_cat).lower().strip() == norm_task_cat and h_rating is not None:
                same_cat_ratings.append(float(h_rating))

    if same_cat_ratings:
        weights = [0.9**i for i in range(len(same_cat_ratings))]
        perf_score = sum((r / 5.0) * w for r, w in zip(same_cat_ratings, weights)) / sum(weights)
        perf_score = min(1.0, max(0.0, perf_score))
    else:
        perf_score = 0.5  # Neutral fallback for no history

    # ── Signal 4: Seniority Fit ───────────────────────────────────────────────
    task_sen = (task_min_seniority or "mid").lower().strip()
    emp_sen = (emp_seniority or "mid").lower().strip()

    task_idx = SENIORITY_LEVELS.index(task_sen) if task_sen in SENIORITY_LEVELS else 1
    emp_idx = SENIORITY_LEVELS.index(emp_sen) if emp_sen in SENIORITY_LEVELS else 1
    gap = emp_idx - task_idx

    if gap >= 0:
        seniority_score = 1.0
    elif gap == -1:
        seniority_score = 0.5
    else:
        seniority_score = 0.0  # 2+ levels under-qualified -> disqualify

    # ── Urgency Weight Shifting ───────────────────────────────────────────────
    hours_left = compute_hours_until(task_deadline)
    is_urgent = hours_left is not None and 0 <= hours_left < settings.URGENCY_DEADLINE_HOURS

    if is_urgent:
        w_skills = settings.URGENCY_WEIGHTS_SKILLS
        w_avail = settings.URGENCY_WEIGHTS_AVAILABILITY
        w_perf = settings.URGENCY_WEIGHTS_PERFORMANCE
        w_sen = settings.URGENCY_WEIGHTS_SENIORITY
    else:
        w_skills = settings.SCORING_WEIGHTS_SKILLS
        w_avail = settings.SCORING_WEIGHTS_AVAILABILITY
        w_perf = settings.SCORING_WEIGHTS_PERFORMANCE
        w_sen = settings.SCORING_WEIGHTS_SENIORITY

    # ── Weighted Sum ──────────────────────────────────────────────────────────
    score = (
        w_skills * skills_score
        + w_avail * avail_score
        + w_perf * perf_score
        + w_sen * seniority_score
    )

    # ── Hard Disqualify Conditions ────────────────────────────────────────────
    if avail_score == 0.0 or seniority_score == 0.0:
        score = 0.0

    return {
        "employee_id": str(emp_id),
        "score": round(min(1.0, max(0.0, score)), 4),
        "is_urgent_applied": is_urgent,
        "breakdown": {
            "skills": round(skills_score, 4),
            "availability": round(avail_score, 4),
            "performance": round(perf_score, 4),
            "seniority": round(seniority_score, 4),
        },
        "details": {
            "matched_skills": list(req_set & emp_set),
            "required_count": len(req_set),
            "active_count": emp_active_count,
            "capacity": capacity,
            "seniority_gap": gap,
            "history_count": len(same_cat_ratings),
        },
    }
