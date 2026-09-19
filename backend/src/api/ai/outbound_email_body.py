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
    if name:
        signing_rule = f"If you sign the email, use only this name: {name}."
    else:
        signing_rule = (
            "Do not add a signature name unless the user explicitly provides one."
        )
    return (
        "Never use placeholders such as [Seu nome], [Your name], [Nome], or similar. "
        f"{signing_rule} "
        "End informational emails on the last useful paragraph, or with a brief natural "
        "closing (e.g. 'Abraço!' or 'Até mais!'). "
        "Never end with 'Abraço,' followed by a name placeholder on the next line."
    )


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
