"""
app/models/email.py — Raw inbound email log. Never deleted.

message_id is the RFC 2822 Message-ID header value — used as an idempotency
key so that Mailgun / Gmail retries cannot create duplicate processing runs.
On INSERT conflict, the worker skips the duplicate and returns the existing row.

timezone is optional in the ingest payload; falls back to settings.ORG_TIMEZONE.
It is stored here so that the extractor can always resolve relative deadlines
without needing to call settings again.
"""
import uuid

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import EmailStatus


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # RFC 2822 Message-ID header — unique constraint enforces idempotency
    message_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    # IANA timezone string, e.g. "Asia/Kolkata". Stored from payload or ORG_TIMEZONE default.
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=EmailStatus.PENDING.value
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
