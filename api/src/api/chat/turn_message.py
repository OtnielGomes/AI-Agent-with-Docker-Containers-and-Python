"""Shape one chat turn the same way the chat route does."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from api.inbound_mail import reply_language

_REPLY_REQUEST = re.compile(
    r"\b(responde|responder|responda|reply|answer)\b",
    re.IGNORECASE,
)


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


def disambiguation_reply(
    message: str, inbound_emails: Sequence[_InboundCard]
) -> str | None:
    """Ask which Inbound email when a Reply request matches more than one."""
    tied = _tied_reply_matches(message, inbound_emails)
    if not tied:
        return None
    listed = ", ou ".join(
        f"{item.sender}, {item.subject}, {item.date}" for item in tied
    )
    if reply_language(message) == "en":
        listed = ", or ".join(
            f"{item.sender}, {item.subject}, {item.date}" for item in tied
        )
        return f"Which email? {listed}?"
    return f"Qual email? {listed}?"


def reply_names_recipient(reply: str, recipient: str | None, message: str) -> str:
    """Keep the Assistant reply naming the Recipient address of one Draft."""
    text = (reply or "").strip()
    if not recipient:
        return text
    if recipient in text and _says_ready(text, message):
        return text
    if recipient in text:
        return f"{text}\n\n{_ready_sentence(message, recipient)}".strip()
    if _says_ready(text, message):
        return f"{text} {recipient}"
    return f"{text}\n\n{_ready_sentence(message, recipient)}".strip()


def with_open_drafts(
    message: str,
    open_drafts: Sequence[_DraftCard],
    inbound_emails: Sequence[_InboundCard],
    pinned_recipient: str | None = None,
) -> str:
    """Give the model the review cards for this turn, oldest first."""
    chat_message = message
    if not open_drafts:
        text = _with_inbound_emails(
            f"{message}\n\nOpen Drafts on the review cards: none.",
            inbound_emails,
        )
        return _with_pinned_recipient(
            text, chat_message, open_drafts, inbound_emails, pinned_recipient
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
    text = _with_inbound_emails(message, inbound_emails)
    return _with_pinned_recipient(
        text, chat_message, open_drafts, inbound_emails, pinned_recipient
    )


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


def _with_pinned_recipient(
    text: str,
    message: str,
    open_drafts: Sequence[_DraftCard],
    inbound_emails: Sequence[_InboundCard],
    pinned_recipient: str | None,
) -> str:
    if not pinned_recipient or open_drafts:
        return text
    if _unique_reply(message, inbound_emails) is not None:
        return text
    return (
        f"{text}\n\n"
        f"Pinned recipient for a new email: {pinned_recipient}. "
        "It is already set. Do not ask for an address. "
        "Call send_me_email without to_email. "
        "A Reply ignores this pin and uses the Inbound sender."
    )


def _says_ready(text: str, message: str) -> bool:
    folded = text.casefold()
    if reply_language(message) == "en":
        return re.search(r"\bready\b", folded) is not None
    return "pronto" in folded or "pronta" in folded


def _ready_sentence(message: str, recipient: str) -> str:
    if reply_language(message) == "en":
        return f"The draft is ready for {recipient}."
    return f"O rascunho está pronto para {recipient}."


def _tied_reply_matches(
    message: str, inbound_emails: Sequence[_InboundCard]
) -> tuple[_InboundCard, ...] | None:
    if not _REPLY_REQUEST.search(message or ""):
        return None
    scored = _scored_replies(message, inbound_emails)
    if len(scored) < 2:
        return None
    if scored[0][0] > scored[1][0]:
        return None
    top = scored[0][0]
    tied_ids = {item.id for score, item in scored if score == top}
    return tuple(item for item in inbound_emails if item.id in tied_ids)


def _unique_reply(
    message: str, inbound_emails: Sequence[_InboundCard]
) -> _InboundCard | None:
    if not _REPLY_REQUEST.search(message or ""):
        return None
    scored = _scored_replies(message, inbound_emails)
    if not scored:
        return None
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][1]
    return None


def _scored_replies(
    message: str, inbound_emails: Sequence[_InboundCard]
) -> list[tuple[int, _InboundCard]]:
    text = (message or "").casefold()
    scored = [
        (score, item)
        for item in inbound_emails
        if (score := _match_score(text, item))
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored


def _match_score(text: str, item: _InboundCard) -> int:
    score = 0
    sender = (item.sender or "").casefold()
    if sender and sender in text:
        score += 3
    else:
        for token in sender.split():
            if len(token) >= 4 and token in text:
                score += 2
                break
    subject = (item.subject or "").casefold()
    if subject and subject in text:
        score += 3
    date = (item.date or "").casefold()
    if date and date in text:
        score += 3
    address = (item.address or "").casefold()
    if address and address in text:
        score += 3
    inbound_id = str(item.id or "").casefold()
    if inbound_id and inbound_id in text:
        score += 3
    return score
