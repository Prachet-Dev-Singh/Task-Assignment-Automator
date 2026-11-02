"""
tests/eval/test_extractor_live.py — Opt-in live evaluation for the extractor.

Calls the REAL Groq API against 10 labelled emails.
Scores extraction quality using precision and recall on required_skills.

Run with:
    pytest tests/eval/ --live -v -s

Without --live this entire file is skipped automatically.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).parent
EMAILS_DIR = EVAL_DIR / "emails"
EXPECTED_DIR = EVAL_DIR / "expected"

SKILL_VOCAB = [
    "sql", "python", "powerbi", "data-analysis", "devops",
    "react", "java", "machine-learning", "testing", "infrastructure",
    "security", "reporting", "software-development",
]
CATEGORY_VOCAB = [
    "data-analysis", "software-development", "devops", "machine-learning",
    "reporting", "testing", "infrastructure", "security", "planning", "general",
]
RECEIVED_AT = datetime(2026, 11, 2, 9, 0, 0, tzinfo=timezone.utc)
TIMEZONE_STR = "Asia/Kolkata"


def _load_cases() -> list[dict]:
    cases = []
    for email_file in sorted(EMAILS_DIR.glob("*.txt")):
        expected_file = EXPECTED_DIR / (email_file.stem + ".json")
        if expected_file.exists():
            cases.append({
                "name": email_file.stem,
                "body": email_file.read_text(encoding="utf-8"),
                "expected": json.loads(expected_file.read_text(encoding="utf-8")),
            })
    return cases


def _score_task(pred: dict, exp: dict) -> dict:
    """Score one predicted task against one expected task."""
    pred_skills = set(pred.get("required_skills", []))
    exp_skills = set(exp.get("required_skills", []))

    precision = len(pred_skills & exp_skills) / len(pred_skills) if pred_skills else (1.0 if not exp_skills else 0.0)
    recall    = len(pred_skills & exp_skills) / len(exp_skills)  if exp_skills  else 1.0

    unmapped_ok = True
    if "unmapped_skills_contains" in exp:
        for skill in exp["unmapped_skills_contains"]:
            if skill not in pred.get("unmapped_skills", []):
                unmapped_ok = False

    return {
        "skill_precision":  round(precision, 2),
        "skill_recall":     round(recall, 2),
        "priority_match":   pred.get("priority") == exp.get("priority"),
        "seniority_match":  pred.get("min_seniority") == exp.get("min_seniority"),
        "category_match":   pred.get("category") == exp.get("category"),
        "deadline_ok":      (pred.get("deadline") is not None) == exp.get("deadline_not_null", False),
        "unmapped_ok":      unmapped_ok,
        "confidence":       pred.get("confidence"),
        "low_conf_flagged": (pred.get("confidence", 1.0) < 0.6) if exp.get("expect_low_confidence") else None,
    }


@pytest.mark.live
def test_extraction_quality():
    """
    Run extraction on all 10 eval emails and print a precision/recall report.
    Fails only if average precision or recall drops below 0.30.
    """
    from app.services.extractor import extract

    cases = _load_cases()
    assert len(cases) >= 10, f"Expected >=10 eval cases, found {len(cases)}"

    all_scores = []
    print("\n\n========== Extractor Eval Report ==========")

    for case in cases:
        print(f"\n--- {case['name']} ---")
        try:
            tasks = extract(
                body=case["body"],
                received_at=RECEIVED_AT,
                timezone_str=TIMEZONE_STR,
                skill_vocab=SKILL_VOCAB,
                category_vocab=CATEGORY_VOCAB,
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue

        expected_tasks = case["expected"].get("tasks", [])
        exp_count = len(expected_tasks)
        pred_count = len(tasks)
        print(f"  Task count: expected={exp_count}, predicted={pred_count}")

        if tasks and expected_tasks:
            score = _score_task(tasks[0], expected_tasks[0])
            all_scores.append(score)
            print(f"  Skill Precision: {score['skill_precision']}")
            print(f"  Skill Recall:    {score['skill_recall']}")
            print(f"  Priority Match:  {score['priority_match']}")
            print(f"  Seniority Match: {score['seniority_match']}")
            print(f"  Category Match:  {score['category_match']}")
            print(f"  Deadline OK:     {score['deadline_ok']}")
            print(f"  Unmapped OK:     {score['unmapped_ok']}")
            print(f"  Confidence:      {score['confidence']}")
            if score["low_conf_flagged"] is not None:
                print(f"  Low-conf flagged correctly: {score['low_conf_flagged']}")
        elif not tasks and not expected_tasks:
            print("  Correctly returned empty tasks array.")

    if all_scores:
        avg_p = sum(s["skill_precision"] for s in all_scores) / len(all_scores)
        avg_r = sum(s["skill_recall"]    for s in all_scores) / len(all_scores)
        print(f"\n========== Aggregate ==========")
        print(f"  Average Skill Precision: {avg_p:.2f}")
        print(f"  Average Skill Recall:    {avg_r:.2f}")
        print(f"  Cases evaluated: {len(all_scores)}/{len(cases)}")
        print("================================\n")

        assert avg_p >= 0.30, f"Average skill precision {avg_p:.2f} is too low — check prompt"
        assert avg_r >= 0.30, f"Average skill recall {avg_r:.2f} is too low — check prompt"
