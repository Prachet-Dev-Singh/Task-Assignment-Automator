"""
scripts/test_assign.py — Standalone CLI test script for Phase 2.

Takes an email text file, extracts task requirements, scores all seeded employees,
and prints the resulting assignment JSON with scoring breakdown and reasoning.
Works in standalone mode using an in-memory database seeded with the 10 canonical employees.

Usage:
    python scripts/test_assign.py --email tests/fixtures/emails/clear_task.txt
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Support UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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

from app.database import Base
from app.models.employee import Employee
from app.models.email import Email
from app.models.task import Task
from app.services.assigner import assign
from app.services.scorer import score_candidate

# Canonical 10 employees data for standalone testing
SAMPLE_EMPLOYEES = [
    {"name": "Arjun Mehta", "email": "arjun@company.com", "role": "Junior Developer", "seniority": "junior", "skills": ["python", "testing", "sql"], "capacity": 2, "is_available": True},
    {"name": "Priya Kapoor", "email": "priya@company.com", "role": "Junior Data Analyst", "seniority": "junior", "skills": ["sql", "data-analysis", "reporting"], "capacity": 2, "is_available": False},  # OOO
    {"name": "Rohan Sharma", "email": "rohan@company.com", "role": "Mid Software Developer", "seniority": "mid", "skills": ["python", "react", "java", "testing", "software-development"], "capacity": 3, "is_available": True},
    {"name": "Sneha Iyer", "email": "sneha@company.com", "role": "Mid Data Analyst", "seniority": "mid", "skills": ["sql", "powerbi", "data-analysis", "reporting"], "capacity": 3, "is_available": True},
    {"name": "Vikram Nair", "email": "vikram@company.com", "role": "Mid DevOps Engineer", "seniority": "mid", "skills": ["devops", "python", "infrastructure", "security"], "capacity": 3, "is_available": True},
    {"name": "Ananya Das", "email": "ananya@company.com", "role": "Mid Software Developer", "seniority": "mid", "skills": ["react", "java", "python", "software-development", "testing"], "capacity": 3, "is_available": True},
    {"name": "Kiran Rao", "email": "kiran@company.com", "role": "Senior Data Scientist", "seniority": "senior", "skills": ["python", "sql", "machine-learning", "data-analysis", "reporting"], "capacity": 4, "is_available": True},
    {"name": "Meera Pillai", "email": "meera@company.com", "role": "Senior Software Developer", "seniority": "senior", "skills": ["java", "react", "python", "software-development", "testing", "sql"], "capacity": 4, "is_available": True},
    {"name": "Suresh Kumar", "email": "suresh@company.com", "role": "Senior DevOps Engineer", "seniority": "senior", "skills": ["devops", "infrastructure", "security", "python"], "capacity": 4, "is_available": False},  # OOO
    {"name": "Divya Singh", "email": "divya@company.com", "role": "Tech Lead", "seniority": "lead", "skills": ["python", "java", "react", "sql", "machine-learning", "devops", "infrastructure", "software-development"], "capacity": 5, "is_available": True},
]


def extract_quick_mock(body: str) -> dict:
    """Fast deterministic parser for test fixture emails without requiring live API keys."""
    import re
    body_lower = body.lower()
    skills = []
    for s in ["powerbi", "sql", "python", "react", "java", "devops", "machine-learning", "testing", "security", "infrastructure"]:
        if s in body_lower:
            skills.append(s)

    seniority = "mid"
    if re.search(r"\blead\b", body_lower):
        seniority = "lead"
    elif re.search(r"\bsenior\b", body_lower):
        seniority = "senior"
    elif re.search(r"\bjunior\b", body_lower) or "starter" in body_lower:
        seniority = "junior"

    priority = "medium"
    if "urgent" in body_lower or "critical" in body_lower:
        priority = "urgent"
    elif "high-priority" in body_lower or "high priority" in body_lower:
        priority = "high"

    category = "general"
    if "dashboard" in body_lower or "analytics" in body_lower or "sql" in body_lower:
        category = "data-analysis"
    elif "devops" in body_lower or "infrastructure" in body_lower:
        category = "devops"
    elif "test" in body_lower:
        category = "testing"
    elif "developer" in body_lower or "react" in body_lower:
        category = "software-development"

    return {
        "task_title": "Extracted Task from CLI",
        "description": body.strip()[:100],
        "deadline": None,
        "priority": priority,
        "required_skills": skills,
        "unmapped_skills": [],
        "min_seniority": seniority,
        "category": category,
        "confidence": 0.92,
    }


def _clean_skills(val):
    if not val:
        return []
    import json
    if isinstance(val, (list, tuple)) and len(val) > 0 and val[0] == "[":
        try:
            val = json.loads("".join(str(c) for c in val))
        except Exception:
            pass
    elif isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return [val]
    return list(val) if isinstance(val, (list, tuple)) else [str(val)]


def main():
    parser = argparse.ArgumentParser(description="Test task assignment CLI")
    parser.add_argument("--email", required=True, help="Path to email text file")
    args = parser.parse_args()

    email_path = Path(args.email)
    if not email_path.exists():
        print(f"Error: File '{args.email}' not found.")
        sys.exit(1)

    raw_email = email_path.read_text(encoding="utf-8")
    print(f"\n[EMAIL] Reading email: {email_path.name}")
    print("--------------------------------------------------")

    # In-memory test DB
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed employees
    employees = []
    for emp_data in SAMPLE_EMPLOYEES:
        emp = Employee(**emp_data)
        session.add(emp)
        employees.append(emp)
    session.commit()

    # Extract task
    task_data = extract_quick_mock(raw_email)
    print(f"[TASK] Extracted Task:")
    print(f"   Required Skills: {task_data['required_skills']}")
    print(f"   Min Seniority:   {task_data['min_seniority']}")
    print(f"   Priority:        {task_data['priority']}")
    print(f"   Category:        {task_data['category']}\n")

    # Persist Task & Email
    email_record = Email(
        message_id=f"cli-{uuid4()}@local",
        sender="sender@company.com",
        subject=email_path.stem,
        body=raw_email,
        received_at=datetime.now(timezone.utc),
    )
    session.add(email_record)
    session.flush()

    task = Task(
        email_id=email_record.id,
        position=0,
        title=task_data["task_title"],
        description=task_data["description"],
        deadline=task_data["deadline"],
        priority=task_data["priority"],
        required_skills=task_data["required_skills"],
        unmapped_skills=task_data["unmapped_skills"],
        min_seniority=task_data["min_seniority"],
        category=task_data["category"],
        llm_confidence=task_data["confidence"],
    )
    session.add(task)
    session.commit()

    # Score candidates
    scored = []
    for emp in employees:
        s = score_candidate(
            task_required_skills=task.required_skills,
            task_min_seniority=task.min_seniority,
            task_category=task.category,
            task_deadline=task.deadline,
            emp_id=emp.id,
            emp_skills=emp.skills,
            emp_seniority=emp.seniority,
            emp_capacity=emp.capacity,
            emp_active_count=0,
            history_records=[],
        )
        scored.append(s)

    # Assign
    assignment = assign(task, scored, session)

    winner = session.get(Employee, assignment.employee_id)

    task_skills = _clean_skills(task.required_skills)
    winner_skills = _clean_skills(winner.skills)

    output = {
        "assignment_id": str(assignment.id),
        "task": {
            "id": str(task.id),
            "title": task.title,
            "priority": task.priority,
            "required_skills": task_skills,
            "min_seniority": task.min_seniority,
        },
        "assignee": {
            "id": str(winner.id),
            "name": winner.name,
            "role": winner.role,
            "seniority": winner.seniority,
            "skills": winner_skills,
        },
        "score": assignment.score,
        "score_breakdown": assignment.score_breakdown,
        "reason": assignment.reason,
        "status": assignment.status,
    }

    print("[ASSIGNMENT] Output (JSON):")
    print(json.dumps(output, indent=2))
    print("--------------------------------------------------\n")


if __name__ == "__main__":
    main()
