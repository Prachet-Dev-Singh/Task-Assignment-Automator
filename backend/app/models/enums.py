"""
app/models/enums.py — Single source of truth for all status enums and transitions.

Rules:
  - TaskStatus.PENDING does NOT exist — pending is an EmailStatus.
    Tasks are created directly in EXTRACTED or REVIEW_REQUIRED state.
  - ACTIVE_TASK_STATUSES defines what counts as "currently loaded" work for
    an employee. Used in scorer.py and assigner.py to count active assignments.
    MUST include both ASSIGNED and IN_PROGRESS — once in_progress, work is
    still being done and the slot is still occupied.
  - VALID_TRANSITIONS is the only place that encodes allowed state changes.
    tracker.py uses this table to reject invalid PATCH /tasks/{id}/status calls.
"""
from enum import Enum


# ── Email statuses ────────────────────────────────────────────────────────────
class EmailStatus(str, Enum):
    PENDING    = "pending"      # received, not yet processed by worker
    PROCESSING = "processing"   # worker picked it up
    PROCESSED  = "processed"    # all tasks extracted and queued for assignment
    FAILED     = "failed"       # worker died; raw email still stored for retry


# ── Task statuses ─────────────────────────────────────────────────────────────
class TaskStatus(str, Enum):
    # Extraction outcomes
    EXTRACTED             = "extracted"               # LLM succeeded, confidence >= threshold
    REVIEW_REQUIRED       = "review_required"          # confidence < threshold — needs human approval
    EXTRACTION_FAILED     = "extraction_failed"        # LLM call or parse error

    # Assignment outcomes
    ASSIGNED              = "assigned"                 # employee assigned, work not started
    UNASSIGNED_NO_ELIGIBLE = "unassigned_no_eligible"  # no eligible employee found

    # In-flight
    IN_PROGRESS           = "in_progress"              # employee started work

    # Terminal
    COMPLETED             = "completed"
    CANCELLED             = "cancelled"

    # Reassignment in progress — task stays in this state while
    # assign_task finds a new employee; transitions back to ASSIGNED.
    REASSIGNED            = "reassigned"


# Active = still consuming an employee's capacity slot
# BOTH assigned and in_progress count — once in_progress, the slot is still taken.
ACTIVE_TASK_STATUSES: frozenset[TaskStatus] = frozenset({
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
})


# Allowed transitions for PATCH /tasks/{id}/status
# States not listed here have no valid outgoing transitions (terminal).
VALID_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.ASSIGNED: frozenset({
        TaskStatus.IN_PROGRESS,
        TaskStatus.CANCELLED,
        TaskStatus.REASSIGNED,
    }),
    TaskStatus.IN_PROGRESS: frozenset({
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
        TaskStatus.REASSIGNED,
    }),
    # Human-approval paths — re-enqueues assign_task
    TaskStatus.REVIEW_REQUIRED: frozenset({
        TaskStatus.EXTRACTED,       # human approves → re-enqueue assignment
    }),
    TaskStatus.UNASSIGNED_NO_ELIGIBLE: frozenset({
        TaskStatus.EXTRACTED,       # manual retry → re-enqueue assignment
    }),
    TaskStatus.EXTRACTION_FAILED: frozenset({
        TaskStatus.EXTRACTED,       # manual retry after fixing prompt
    }),
    # REASSIGNED transitions back to ASSIGNED once assign_task completes
    TaskStatus.REASSIGNED: frozenset({
        TaskStatus.ASSIGNED,        # set by assign_task worker on success
        TaskStatus.UNASSIGNED_NO_ELIGIBLE,  # set by assign_task if no one available
    }),
}


# ── Assignment statuses ───────────────────────────────────────────────────────
class AssignmentStatus(str, Enum):
    ASSIGNED    = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    SUPERSEDED  = "superseded"   # previous assignment when task is reassigned
