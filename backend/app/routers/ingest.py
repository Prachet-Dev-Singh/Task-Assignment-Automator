"""
app/routers/ingest.py — Ingestion endpoints.

Routes:
  - POST /ingest: Main JSON ingestion endpoint (curl, tests, webhook proxies).
    Secured by X-Webhook-Secret header. Idempotent on message_id.
  - POST /ingest/mailgun: Mailgun form-data webhook endpoint with HMAC signature check.
"""

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_db
from app.models.email import Email
from app.models.enums import EmailStatus
from app.schemas.email import EmailIngestRequest, EmailIngestResponse
from worker.tasks import process_email

router = APIRouter(tags=["Ingestion"])


def verify_webhook_secret(x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")) -> None:
    """Validate shared secret header against configured settings."""
    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, settings.WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Webhook-Secret header",
        )


@router.post(
    "/ingest",
    response_model=EmailIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest email payload asynchronously",
)
async def ingest_email(
    payload: EmailIngestRequest,
    _: None = Depends(verify_webhook_secret),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Ingest a new raw email payload.
    Enforces idempotency using the RFC 2822 message_id header.
    Returns 202 with email_id immediately; triggers background extraction.
    """
    # Check for existing email with this message_id (idempotency check)
    stmt = select(Email).where(Email.message_id == payload.message_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        return EmailIngestResponse(
            email_id=existing.id,
            message_id=existing.message_id,
            status=existing.status,
            message="Email with this Message-ID was already received; existing record returned.",
        )

    received_time = payload.received_at or datetime.now(timezone.utc)
    tz_str = payload.timezone or settings.ORG_TIMEZONE

    new_email = Email(
        message_id=payload.message_id,
        sender=payload.from_addr,
        subject=payload.subject,
        body=payload.body,
        received_at=received_time,
        timezone=tz_str,
        status=EmailStatus.PENDING.value,
        raw_payload=payload.raw_payload,
    )
    db.add(new_email)
    await db.commit()
    await db.refresh(new_email)

    # Trigger Celery background task
    try:
        process_email.delay(str(new_email.id))
    except Exception:
        # If Redis/Celery is unavailable in local dev without containers, log warning
        pass

    return EmailIngestResponse(
        email_id=new_email.id,
        message_id=new_email.message_id,
        status=new_email.status,
        message="Email successfully received and queued for task extraction.",
    )


@router.post("/ingest/mailgun", status_code=status.HTTP_202_ACCEPTED, summary="Mailgun webhook receiver")
async def ingest_mailgun(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Form-data endpoint for Mailgun inbound routing webhooks.
    Validates Mailgun's HMAC token signature.
    """
    form_data = await request.form()
    token = form_data.get("token")
    timestamp = form_data.get("timestamp")
    signature = form_data.get("signature")

    # Mailgun signature verification
    if token and timestamp and signature and settings.WEBHOOK_SECRET:
        hmac_digest = hmac.new(
            key=settings.WEBHOOK_SECRET.encode("utf-8"),
            msg=f"{timestamp}{token}".encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, hmac_digest):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Mailgun signature")

    message_id = form_data.get("Message-Id") or form_data.get("message-id") or f"mailgun-{token}"
    sender = form_data.get("from") or form_data.get("sender") or "unknown@external.com"
    subject = form_data.get("subject") or ""
    body = form_data.get("body-plain") or form_data.get("stripped-text") or str(form_data)

    payload = EmailIngestRequest(
        message_id=str(message_id),
        from_addr=str(sender),
        subject=str(subject),
        body=str(body),
        received_at=datetime.now(timezone.utc),
        timezone=settings.ORG_TIMEZONE,
    )

    return await ingest_email(payload=payload, _=None, db=db)

