# Imports:
from __future__ import annotations

import os
import uuid
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from sqlmodel import Session

from api.ai.services import generate_email_message
from api.db import engine
from api.drafts import create_open_draft, revise_open_draft
from api.myemailer.inbox_reader import read_inbox


_MAX_BODY_CHARS = 1500
_MAX_TOOL_OUTPUT_CHARS = 12000


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
    #print(config)
    #metadata = config.get("metadata",)
    #add_field = metadata.get("additional_field")
    #print("add_field",add_field)
    response = generate_email_message(query)
    msg = f"Subject: {response.subject}:\nBody: {response.contents}"

    return msg

@tool
def send_me_email(
    subject: str,
    content: str,
    to_email: str | None = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> str:
    """Create an email Draft with a subject and plain-text content.

    Args:
        subject: The subject of the email.
        content: The content of the email.
        to_email: Optional recipient. Omit to use the default inbox address
            or the recipient selected in the UI for this request.
    """
    try:
        pinned = None
        if config:
            pinned = config.get("configurable", {}).get("to_email")
        with Session(engine) as session:
            draft = create_open_draft(
                session,
                subject=subject,
                body=content,
                pinned=pinned,
                named=to_email,
                default=os.environ.get("EMAIL_ADDRESS"),
                sender_name=os.environ.get("EMAIL_SENDER_NAME"),
            )
    except Exception as e:
        return f"Error creating email draft: {e}"
    return (
        f"Draft created for {draft.recipient} with subject {draft.subject}. "
        "It will be sent only after the human confirms it in the chat UI."
    )


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
        with Session(engine) as session:
            draft = revise_open_draft(
                session,
                parsed_id,
                subject=subject,
                body=content,
                recipient=_optional_recipient(recipient),
                sender_name=os.environ.get("EMAIL_SENDER_NAME"),
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
    try:
        emails = read_inbox(
            hours_ago=hours_ago,
            unread_only=True,
            verbose=False,
        )
    except Exception as e:
        return f"Error getting unread emails: {e}"

    return _format_emails_for_tool(emails)