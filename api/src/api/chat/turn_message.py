"""Shape one chat turn the same way the chat route does."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _DraftCard(Protocol):
    id: str
    subject: str
    body: str
    recipient: str


class _InboundCard(Protocol):
    id: str
    sender: str
    address: str
    subject: str
    date: str
    body: str


def inbound_record(item: _InboundCard) -> dict[str, object]:
    return {
        "id": item.id,
        "sender": item.sender,
        "address": item.address,
        "subject": item.subject,
        "date": item.date,
        "body": item.body,
        "unread": getattr(item, "unread", True),
    }


def with_open_drafts(
    message: str,
    open_drafts: Sequence[_DraftCard],
    inbound_emails: Sequence[_InboundCard],
) -> str:
    """Give the model the review cards for this turn, oldest first."""
    if not open_drafts:
        return _with_inbound_emails(
            f"{message}\n\nOpen Drafts on the review cards: none.",
            inbound_emails,
        )

    blocks: list[str] = []
    for index, draft in enumerate(open_drafts, start=1):
        blocks.append(
            f"{index}. id: {draft.id}\n"
            f"subject: {draft.subject}\n"
            f"recipient: {draft.recipient}\n"
            f"body:\n{draft.body}"
        )
    listed = "\n\n".join(blocks)
    message = (
        f"{message}\n\n"
        "Open Drafts on the review cards, oldest at the top:\n\n"
        f"{listed}"
    )
    return _with_inbound_emails(message, inbound_emails)


def _with_inbound_emails(message: str, inbound_emails: Sequence[_InboundCard]) -> str:
    if not inbound_emails:
        return message
    blocks: list[str] = []
    for item in inbound_emails:
        blocks.append(
            f"id: {item.id}\n"
            f"sender: {item.sender}\n"
            f"address: {item.address}\n"
            f"subject: {item.subject}\n"
            f"date: {item.date}\n"
            f"body:\n{item.body}"
        )
    listed = "\n\n".join(blocks)
    return (
        f"{message}\n\n"
        "Inbound emails in the inbox list, newest first:\n\n"
        f"{listed}"
    )
