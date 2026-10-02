# Imports:
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from sqlmodel import Session

from api.chat.turn_message import inbound_record
from api.drafts import create_open_draft, remember_reply_target, revise_open_draft
from api.myemailer.inbox_reader import read_inbox


_MAX_BODY_CHARS = 1500
_MAX_TOOL_OUTPUT_CHARS = 12000


@dataclass(frozen=True)
class CaseTools:
    """Draft store and inbox for one Evaluation case."""

    session: Session
    default_inbox: str | None
    sender_name: str | None
    inbound_emails: tuple[Any, ...]


_case_tools: ContextVar[CaseTools | None] = ContextVar("case_tools", default=None)
_reply_inbounds: ContextVar[tuple[Any, ...]] = ContextVar(
    "reply_inbounds", default=()
)


@contextmanager
def use_reply_inbounds(emails: tuple[Any, ...] | list[Any]) -> Iterator[None]:
    """Let a Reply see the Inbound email bodies for this turn."""
    token = _reply_inbounds.set(tuple(emails))
    try:
        yield
    finally:
        _reply_inbounds.reset(token)


@contextmanager
def use_case_tools(binding: CaseTools) -> Iterator[None]:
    """Point the inbox and Draft tools at one case. The mailbox stays closed."""
    token = _case_tools.set(binding)
    inbound_token = _reply_inbounds.set(tuple(binding.inbound_emails))
    try:
        yield
    finally:
        _reply_inbounds.reset(inbound_token)
        _case_tools.reset(token)


def _tool_session():
    binding = _case_tools.get()
    if binding is not None:
        return nullcontext(binding.session)
    from api.db import engine

    return Session(engine)


def _draft_defaults() -> tuple[str | None, str | None]:
    binding = _case_tools.get()
    if binding is not None:
        return binding.default_inbox, binding.sender_name
    return os.environ.get("EMAIL_ADDRESS"), os.environ.get("EMAIL_SENDER_NAME")


def _case_inbox(unread_only: bool) -> list[dict] | None:
    """The case list is the whole inbox. None means this is not a case."""
    binding = _case_tools.get()
    if binding is None:
        return None
    chosen = binding.inbound_emails
    if unread_only:
        chosen = tuple(item for item in chosen if getattr(item, "unread", True))
    return [inbound_record(item) for item in chosen]


def _format_emails_for_tool(emails: list[dict]) -> str:
    """Format parsed inbox emails for LLM consumption."""
    if not emails:
        return "No emails found matching the criteria."

    cleaned: list[str] = []
    for email in emails:
        data = email.copy()
        data.pop("html_body", None)
        if "body" in data and isinstance(data["body"], str):
            body = data["body"]
            if len(body) > _MAX_BODY_CHARS:
                data["body"] = body[:_MAX_BODY_CHARS] + "…"
        parts = [f"{key}:\t{value}" for key, value in data.items()]
        cleaned.append("\n".join(parts))

    result = "\n-----\n".join(cleaned)
    if len(result) > _MAX_TOOL_OUTPUT_CHARS:
        return result[:_MAX_TOOL_OUTPUT_CHARS] + "\n… (truncated)"
    return result

@tool
def research_email(query:str):
    """
    Research an email based on a query.

    Args:
        query: The query to research.
    """
    from api.ai.services import generate_email_message
    from api.ai.turn_usage import mark_research_called, note_research_draft

    mark_research_called()
    response = generate_email_message(query)
    note_research_draft(response.subject, response.contents)
    msg = f"Subject: {response.subject}:\nBody: {response.contents}"

    return msg

@tool
def send_me_email(
    subject: str,
    content: str,
    to_email: str | None = None,
    reply: bool = False,
    inbound_id: str | None = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> str:
    """Create an email Draft with a subject and plain-text content.

    Args:
        subject: The subject of the email.
        content: The content of the email.
        to_email: Optional recipient. Omit to use the default inbox address
            or the recipient selected in the UI for this request.
            Required when reply is true: the Inbound email's sender address.
        reply: True when this Draft answers one Inbound email. The pinned
            recipient is ignored.
        inbound_id: Stable id of that Inbound email. Omit unless reply is true.
    """
    if reply and not (to_email and to_email.strip()):
        return "Error creating email draft: a Reply needs the sender address."
    if reply:
        rewritten = _reply_without_inbound_copy(content, _inbound_body(inbound_id))
        if rewritten is None:
            return (
                "Error creating email draft: the body copies the Inbound email. "
                "Write your own answer without that body and call send_me_email again."
            )
        content = rewritten
    try:
        pinned = None
        if config and not reply:
            pinned = config.get("configurable", {}).get("to_email")
        default_inbox, sender_name = _draft_defaults()
        with _tool_session() as session:
            draft = create_open_draft(
                session,
                subject=subject,
                body=content,
                pinned=pinned,
                named=to_email,
                default=default_inbox,
                sender_name=sender_name,
                ignore_pinned=reply,
            )
        if reply:
            remember_reply_target(str(draft.id), inbound_id)
    except Exception as e:
        return f"Error creating email draft: {e}"
    return (
        f"Draft created for {draft.recipient} with subject {draft.subject}. "
        "It will be sent only after the human confirms it in the chat UI."
    )


def _inbound_body(inbound_id: str | None) -> str:
    if not inbound_id:
        return ""
    for item in _reply_inbounds.get():
        if getattr(item, "id", None) == inbound_id:
            body = getattr(item, "body", "") or ""
            return body.strip()
    return ""


def _reply_without_inbound_copy(content: str, inbound_body: str) -> str | None:
    """Drop a pasted Inbound email body. None means the Reply has no answer left."""
    if not inbound_body or inbound_body not in (content or ""):
        return content
    stripped = "\n".join(
        line for line in content.replace(inbound_body, "").splitlines()
    )
    while "\n\n\n" in stripped:
        stripped = stripped.replace("\n\n\n", "\n\n")
    stripped = stripped.strip()
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) <= 2:
        return None
    return stripped


def _optional_recipient(recipient: str | None) -> str | None:
    if recipient is None:
        return None
    stripped = recipient.strip()
    return stripped or None


@tool
def revise_email_draft(
    draft_id: str,
    subject: str,
    content: str,
    recipient: str | None = None,
) -> str:
    """Revise one open Draft in place. Do not use this to create a new email.

    Args:
        draft_id: Id of the open Draft shown on the review card.
        subject: New subject, in the Draft's language unless the user asked for another.
        content: New plain-text body, revised from the body shown on the review card.
        recipient: New Recipient. Omit unless the user asked to change the Recipient.
    """
    try:
        parsed_id = uuid.UUID(draft_id)
    except ValueError:
        return f"Error revising email draft: invalid id {draft_id}"
    try:
        _, sender_name = _draft_defaults()
        with _tool_session() as session:
            draft = revise_open_draft(
                session,
                parsed_id,
                subject=subject,
                body=content,
                recipient=_optional_recipient(recipient),
                sender_name=sender_name,
            )
    except Exception as e:
        return f"Error revising email draft: {e}"
    return (
        f"Draft revised for {draft.recipient} with subject {draft.subject}. "
        "It will be sent only after the human confirms it in the chat UI."
    )


@tool
def get_recent_emails(
    limit: int = 10,
    hours_ago: int = 168,
    unread_only: bool = False,
) -> str:
    """
    Fetch recent inbox emails for reading, listing, or summarizing.

    Args:
        limit: Maximum number of emails to return (most recent first).
        hours_ago: How far back to search, in hours (default 7 days).
        unread_only: If True, return only unread emails.
    """
    case_emails = _case_inbox(unread_only)
    if case_emails is not None:
        return _format_emails_for_tool(case_emails[:limit])
    try:
        emails = read_inbox(
            hours_ago=hours_ago,
            unread_only=unread_only,
            limit=limit,
            verbose=False,
        )
    except Exception as e:
        return f"Error getting recent emails: {e}"

    return _format_emails_for_tool(emails)


@tool
def get_unread_emails(hours_ago: int = 48) -> str:
    """
    Get unread emails from the inbox.

    Args:
        hours_ago: The number of hours ago to get unread emails from.
    """
    case_emails = _case_inbox(True)
    if case_emails is not None:
        return _format_emails_for_tool(case_emails)
    try:
        emails = read_inbox(
            hours_ago=hours_ago,
            unread_only=True,
            verbose=False,
        )
    except Exception as e:
        return f"Error getting unread emails: {e}"

    return _format_emails_for_tool(emails)