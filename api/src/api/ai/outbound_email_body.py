"""Prepare an Outbound email body for sending."""

from __future__ import annotations

import re

_PLACEHOLDER_PATTERN = re.compile(
    r"\[(?:Seu nome|Your name|Nome do remetente|Nome|Name)\]",
    re.IGNORECASE,
)

_ORPHAN_CLOSING_LINES = re.compile(
    r"^\s*(?:Abraços?|Atenciosamente|Cordialmente|Best regards|Sincerely),?\s*$",
    re.IGNORECASE,
)


def outbound_email_body_generation_hint(sender_name: str) -> str:
    name = (sender_name or "").strip()
    configured = name if name else "none"
    return (
        "Write the outbound email as a short human letter. "
        "The body starts with an Opening, then the content, a Lead-in when the content "
        "needs introducing (a list, a summary, or an invitation), and a Closing as the last line. "
        'Portuguese Opening is "Olá," and Closing is "Até mais!". '
        'English Opening is "Hello," and Closing is "Talk soon!". '
        "Any other language uses a conventional greeting and farewell in that language. "
        "When the user's message states a person's name, the Opening greets them by that name "
        '(for example "Olá Otniel,"). When it states none, greet without inventing a name. '
        "The subject uses the same language as the body. "
        "The body language is the language the user's message asks for; otherwise the language "
        "that message is written in. "
        "A revision keeps the Draft's current language unless the user asks for another language. "
        f"Do not add a signature name. A configured sender name ({configured}) is not written "
        "after the Closing. "
        "Never use placeholders such as [Seu nome], [Your name], [Nome], or similar. "
        "The body contains no offer of further work."
    )


def prepare_assistant_outbound_email_body(
    raw: str, sender_name: str | None = None
) -> str:
    """Normalize an assistant-written body before it is stored."""
    text = prepare_outbound_email_body(raw)
    name = (sender_name or "").strip()
    if not name:
        return text

    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].strip().casefold() != name.casefold():
        return text

    lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def prepare_outbound_email_body(raw: str) -> str:
    text = _PLACEHOLDER_PATTERN.sub("", raw)
    lines = text.splitlines()
    cleaned: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _PLACEHOLDER_PATTERN.search(stripped):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        cleaned.append(line)

    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    if cleaned and _ORPHAN_CLOSING_LINES.match(cleaned[-1].strip()):
        if len(cleaned) >= 2 and not cleaned[-2].strip():
            cleaned.pop()
        elif len(cleaned) == 1:
            cleaned.pop()

    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
