"""Helpers for extracting user-facing text from LangGraph message history."""

from __future__ import annotations

_TRANSFER_PHRASES = (
    "transferring back",
    "successfully transferred",
    "initiated a transfer",
    "will handle it from here",
    "have been provided",
    "provided above",
)

_WORKER_AGENT_NAMES = frozenset({"email_agent", "research_agent"})


def _message_content(message: object) -> str:
    """Return string content from a LangChain message object."""
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


def _is_transfer_or_meta_message(message: object, content: str) -> bool:
    """Return True when the message is routing noise, not a user reply."""
    normalized = content.lower()
    if any(phrase in normalized for phrase in _TRANSFER_PHRASES):
        return True

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls and len(normalized) < 120:
        return True

    return False


def extract_assistant_reply(messages: list[object]) -> str:
    """Pick the best assistant message to show in the chat UI."""
    for message in reversed(messages):
        if type(message).__name__ != "AIMessage":
            continue
        content = _message_content(message)
        if not content or _is_transfer_or_meta_message(message, content):
            continue
        if getattr(message, "name", None) in _WORKER_AGENT_NAMES:
            return content

    for message in reversed(messages):
        if type(message).__name__ != "AIMessage":
            continue
        content = _message_content(message)
        if content and not _is_transfer_or_meta_message(message, content):
            return content

    if messages:
        fallback = _message_content(messages[-1])
        if fallback:
            return fallback

    return "No response generated."
