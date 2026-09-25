"""Inbox listing, mark-read, and Reply creation for the chat chrome."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from api.ai.services import generate_email_message
from api.db import get_session
from api.drafts import create_open_draft, draft_as_chat_item
from api.inbound_mail import INBOUND_DAYS, INBOUND_LIMIT, compose_reply, to_inbound_item
from api.myemailer.inbox_reader import mark_inbound_read, read_inbox

router = APIRouter()


def list_inbound_emails() -> list[dict]:
    emails = read_inbox(
        hours_ago=INBOUND_DAYS * 24,
        unread_only=False,
        limit=INBOUND_LIMIT,
        verbose=False,
    )
    items: list[dict] = []
    for email in emails:
        item = to_inbound_item(email)
        if item is not None:
            items.append(item)
    return items


def _find_inbound(email_id: str) -> dict:
    for item in list_inbound_emails():
        if item["id"] == email_id:
            return item
    raise LookupError(email_id)


@router.get("/")
def get_inbox(limit: int = INBOUND_LIMIT, days: int = INBOUND_DAYS):
    """The chrome's listing: inbox only, ten most recent, last seven days."""
    del limit, days
    try:
        return {"emails": list_inbound_emails()}
    except Exception:
        raise HTTPException(status_code=502, detail="Could not load the inbox.")


@router.post("/{email_id}/read")
def mark_read(email_id: str):
    try:
        mark_inbound_read(email_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Could not mark the email read.")
    return {"id": email_id, "unread": False}


@router.post("/{email_id}/reply")
def create_reply(email_id: str, session: Session = Depends(get_session)):
    try:
        item = _find_inbound(email_id)
        composed = compose_reply(item, lambda instruction: generate_email_message(instruction).contents)
    except LookupError:
        raise HTTPException(status_code=404, detail="Inbound email not found.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid sender address.")
    except Exception:
        raise HTTPException(status_code=502, detail="Could not create the reply.")

    draft = create_open_draft(
        session,
        subject=composed["subject"],
        body=composed["body"],
        pinned=None,
        named=composed["recipient"],
        default=os.environ.get("EMAIL_ADDRESS"),
        sender_name=os.environ.get("EMAIL_SENDER_NAME"),
        ignore_pinned=True,
    )
    return draft_as_chat_item(draft)
