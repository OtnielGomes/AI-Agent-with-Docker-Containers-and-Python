"""Outbound email Drafts: persist for review, send only on Confirm."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from sqlmodel import DateTime, Field, Session, SQLModel, col, select

from api.ai.outbound_email_body import prepare_outbound_email_body
from api.myemailer.recipient import resolve_recipient, validated_recipient

DRAFT_OPEN = "open"
DRAFT_SENT = "sent"
DRAFT_DISCARDED = "discarded"


class DraftError(Exception):
    """Base error for Draft operations."""


class DraftNotFoundError(DraftError):
    """Raised when a Draft id does not exist."""


class DraftNotOpenError(DraftError):
    """Raised when Confirm or Discard targets a non-open Draft."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Draft(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    subject: str
    body: str
    recipient: str
    state: str = Field(default=DRAFT_OPEN, index=True)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


_created_in_turn: ContextVar[list[Draft] | None] = ContextVar(
    "created_in_turn", default=None
)


def _require_open_draft(session: Session, draft_id: uuid.UUID) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise DraftNotFoundError(f"Draft not found: {draft_id}")
    if draft.state != DRAFT_OPEN:
        raise DraftNotOpenError(f"Draft is not open: {draft_id}")
    return draft


def create_open_draft(
    session: Session,
    *,
    subject: str,
    body: str,
    pinned: str | None,
    named: str | None,
    default: str | None,
) -> Draft:
    recipient = resolve_recipient(pinned=pinned, named=named, default=default)
    prepared = prepare_outbound_email_body(body)
    draft = Draft(
        subject=subject,
        body=prepared,
        recipient=recipient,
        state=DRAFT_OPEN,
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    bucket = _created_in_turn.get()
    if bucket is not None:
        bucket.append(draft)
    return draft


def confirm_draft(
    session: Session,
    draft_id: uuid.UUID,
    *,
    subject: str,
    body: str,
    recipient: str,
    send_mail: Callable[..., Any],
) -> Draft:
    draft = _require_open_draft(session, draft_id)

    prepared = prepare_outbound_email_body(body)
    resolved = validated_recipient(recipient)

    draft.subject = subject
    draft.body = prepared
    draft.recipient = resolved
    session.add(draft)
    session.commit()
    session.refresh(draft)

    send_mail(subject=subject, content=prepared, to_email=resolved)

    draft.state = DRAFT_SENT
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


@contextmanager
def collecting_created_drafts() -> Iterator[list[Draft]]:
    bucket: list[Draft] = []
    token = _created_in_turn.set(bucket)
    try:
        yield bucket
    finally:
        _created_in_turn.reset(token)


def draft_as_chat_item(draft: Draft) -> dict[str, str]:
    return {
        "id": str(draft.id),
        "subject": draft.subject,
        "body": draft.body,
        "recipient": draft.recipient,
        "state": draft.state,
    }


def chat_turn_payload(content: str, drafts: list[Draft]) -> dict[str, Any]:
    return {
        "content": content,
        "drafts": [draft_as_chat_item(item) for item in drafts],
    }


def discard_draft(session: Session, draft_id: uuid.UUID) -> Draft:
    draft = _require_open_draft(session, draft_id)

    draft.state = DRAFT_DISCARDED
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def list_open_drafts(session: Session) -> list[Draft]:
    statement = (
        select(Draft)
        .where(col(Draft.state) == DRAFT_OPEN)
        .order_by(col(Draft.created_at))
    )
    return list(session.exec(statement).all())
