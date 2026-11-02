"""Initial schema — all 5 tables plus GIN indexes and partial unique index.

Revision ID: 0001
Revises: 
Create Date: 2026-11-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── employees ─────────────────────────────────────────────────────────────
    op.create_table(
        "employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("seniority", sa.String, nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("capacity", sa.Integer, nullable=False, server_default="3"),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # GIN index for fast skill overlap queries using the && operator
    op.create_index(
        "idx_employee_skills", "employees", ["skills"],
        postgresql_using="gin"
    )

    # ── emails ────────────────────────────────────────────────────────────────
    op.create_table(
        "emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", sa.Text, unique=True, nullable=False),
        sa.Column("sender", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.Text, nullable=False, server_default="UTC"),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("raw_payload", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── tasks ─────────────────────────────────────────────────────────────────
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("emails.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.String, nullable=False, server_default="medium"),
        sa.Column("required_skills", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("unmapped_skills", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("min_seniority", sa.String, nullable=False, server_default="mid"),
        sa.Column("category", sa.String, nullable=True),
        sa.Column("llm_confidence", sa.Float, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="extracted"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("email_id", "position", name="uq_tasks_email_position"),
    )
    # GIN index for fast required_skills overlap queries
    op.create_index(
        "idx_task_skills", "tasks", ["required_skills"],
        postgresql_using="gin"
    )

    # ── assignments ───────────────────────────────────────────────────────────
    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="assigned"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rating", sa.Float, nullable=True),
    )
    # Partial unique index — at most one active assignment per task
    # Prevents double-assignment even if SELECT..FOR UPDATE is bypassed
    op.execute(
        """
        CREATE UNIQUE INDEX uq_assignments_active_task
          ON assignments(task_id)
          WHERE status IN ('assigned', 'in_progress')
        """
    )

    # ── task_history ──────────────────────────────────────────────────────────
    op.create_table(
        "task_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("rating", sa.Float, nullable=True),
        sa.Column("on_time", sa.Boolean, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("task_history")
    op.execute("DROP INDEX IF EXISTS uq_assignments_active_task")
    op.drop_table("assignments")
    op.drop_index("idx_task_skills", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("emails")
    op.drop_index("idx_employee_skills", table_name="employees")
    op.drop_table("employees")

