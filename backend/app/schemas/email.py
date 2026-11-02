"""
app/schemas/email.py — Pydantic schemas for email ingestion and status queries.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EmailIngestRequest(BaseModel):
    """
    Inbound email payload.
    Supports 'from' in JSON via alias 'from_addr'.
    """
    model_config = ConfigDict(populate_by_name=True)

    message_id: str = Field(..., description="RFC 2822 Message-ID header for idempotency")
    from_addr: str = Field(..., alias="from", description="Sender email address")
    subject: Optional[str] = Field(None, description="Email subject")
    body: str = Field(..., min_length=1, description="Raw email text body")
    received_at: Optional[datetime] = Field(None, description="ISO timestamp when email arrived")
    timezone: Optional[str] = Field(None, description="IANA timezone name e.g. Asia/Kolkata")
    raw_payload: Optional[dict[str, Any]] = Field(None, description="Original raw provider webhook payload")


class EmailIngestResponse(BaseModel):
    email_id: UUID
    message_id: str
    status: str
    message: str


class EmailTaskSummary(BaseModel):
    id: UUID
    position: int
    title: str
    status: str
    priority: str
    confidence: Optional[float] = None


class EmailDetailResponse(BaseModel):
    id: UUID
    message_id: str
    sender: str
    subject: Optional[str]
    received_at: datetime
    timezone: str
    status: str
    created_at: datetime
    tasks: list[EmailTaskSummary] = []

