# Imports:
from __future__ import annotations

import os
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from api.myemailer.sender import send_mail
from api.myemailer.inbox_reader import read_inbox
from api.myemailer.validation import is_valid_email
from api.ai.services import generate_email_message


def _resolve_recipient(
    config: RunnableConfig | None,
    tool_to_email: str | None = None,
) -> str:
    """Pick recipient: request config overrides tool arg, then env default."""
    configured = None
    if config:
        configured = config.get("configurable", {}).get("to_email")
    recipient = configured or tool_to_email or os.environ.get("EMAIL_ADDRESS")
    if not recipient:
        raise ValueError("No recipient email configured.")
    if not is_valid_email(recipient):
        raise ValueError(f"Invalid recipient email: {recipient}")
    return recipient.strip()

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
    """Send an email with a subject and plain-text content.

    Args:
        subject: The subject of the email.
        content: The content of the email.
        to_email: Optional recipient. Omit to use the default inbox address
            or the recipient selected in the UI for this request.
    """
    try:
        recipient = _resolve_recipient(config, to_email)
        send_mail(subject=subject, content=content, to_email=recipient)
    except Exception as e:
        return f"Error sending email: {e}"
    return f"Email sent successfully to {recipient}."


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