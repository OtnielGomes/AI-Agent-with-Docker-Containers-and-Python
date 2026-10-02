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


_RESEARCH_REQUEST = re.compile(
    r"\b(pesquisa|pesquisar|pesquise|research)\b",
    re.IGNORECASE,
)
_NEW_OUTBOUND = re.compile(
    r"\b(manda|mandar|enviar|envie|envia|send)\b",
    re.IGNORECASE,
)


def _valid_addresses(message: str) -> list[str]:
    from api.myemailer.validation import is_valid_email

    found: list[str] = []
    for token in (message or "").split():
        cleaned = token.strip(".,;:!?()[]<>\"'")
        if is_valid_email(cleaned) and cleaned not in found:
            found.append(cleaned)
    return found


def named_recipient(message: str) -> str | None:
    """The one valid address written in a Chat message. A person's name is not one."""
    found = _valid_addresses(message)
    if len(found) == 1:
        return found[0]
    return None


def _invalid_address(message: str) -> bool:
    from api.myemailer.validation import is_valid_email

    for token in (message or "").split():
        cleaned = token.strip(".,;:!?()[]<>\"'")
        if "@" in cleaned and not is_valid_email(cleaned):
            return True
    return False


def recipient_question(
    message: str,
    pinned_recipient: str | None,
    default_inbox: str | None = None,
) -> str | None:
    """Ask before storing when the Recipient is missing, ambiguous, or not valid."""
    if pinned_recipient or not asks_for_new_outbound(message):
        return None
    addresses = _valid_addresses(message)
    english = reply_language(message) == "en"
    if len(addresses) >= 2:
        listed = " or ".join(addresses) if english else " ou ".join(addresses)
        if english:
            return f"Which address? {listed}."
        return f"Qual endereço? {listed}."
    if _invalid_address(message):
        if english:
            return "Give a valid recipient."
        return "Informe um destinatário válido."
    if not addresses and not (default_inbox or "").strip():
        if english:
            return "Who is the recipient?"
        return "Qual é o destinatário?"
    return None


_REVISION_REQUEST = re.compile(
    r"\b(esse email|este email|this email|outro fechamento|another closing)\b",
    re.IGNORECASE,
)
_REQUESTED_SUBJECT = re.compile(
    r"\b(?:assunto|subject)\s+(.+?)\s*$",
    re.IGNORECASE,
)


def is_revision_request(message: str) -> bool:
    """A Chat message that changes an open Draft, even when it says manda."""
    return _REVISION_REQUEST.search(message or "") is not None


def requested_subject(message: str) -> str | None:
    match = _REQUESTED_SUBJECT.search((message or "").strip())
    if match is None:
        return None
    subject = match.group(1).strip()
    subject = re.sub(r"^(?:para|to)\s+", "", subject, flags=re.IGNORECASE).strip()
    subject = subject.strip(".,;:!?")
    return subject or None


_SUBJECT_CHANGE = re.compile(
    r"\b(muda|mudar|altere|altera|change)\b",
    re.IGNORECASE,
)


def asks_for_both(message: str) -> bool:
    """A new Outbound email and a Revision in the same Chat message."""
    if is_revision_request(message) or not asks_for_new_outbound(message):
        return False
    return requested_subject(message) is not None and _SUBJECT_CHANGE.search(
        message or ""
    ) is not None


def asks_for_new_outbound(message: str) -> bool:
    """A Chat message that asks for a new Outbound email.

    The words email, emails, and e-mail do not ask.
    """
    return _NEW_OUTBOUND.search(message or "") is not None


def asks_for_researched_email(message: str) -> bool:
    """A Chat message that asks for research and an Outbound email."""
    text = message or ""
    return (
        _RESEARCH_REQUEST.search(text) is not None
        and asks_for_new_outbound(text)
    )


def researched_outbound(
    chat_message: str,
    messages: Sequence[object],
    remembered: Sequence[tuple[str, str]] = (),
) -> tuple[str, str] | None:
    """Subject and body from research when that Chat message asks to email it."""
    if not asks_for_researched_email(chat_message):
        return None
    for subject, body in reversed(tuple(remembered)):
        cleaned_subject = subject.strip()
        cleaned_body = body.strip()
        if cleaned_subject and cleaned_body:
            return cleaned_subject, cleaned_body
    for message in reversed(tuple(messages)):
        if getattr(message, "name", None) != "research_email":
            continue
        parsed = _parse_research_email(_message_text(message))
        if parsed is not None:
            return parsed
    return None


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts).strip()
    return str(content).strip()


def _parse_research_email(text: str) -> tuple[str, str] | None:
    prefix = "Subject: "
    marker = ":\nBody: "
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix) :]
    index = rest.find(marker)
    if index <= 0:
        return None
    subject = rest[:index].strip()
    body = rest[index + len(marker) :].strip()
    if not subject or not body:
        return None
    return subject, body


def reply_names_recipient(reply: str, recipient: str | None, message: str) -> str:
    """The Assistant reply for one Draft says it is ready and names that Recipient."""
    if not recipient:
        return (reply or "").strip()
    return _ready_sentence(message, recipient)


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
