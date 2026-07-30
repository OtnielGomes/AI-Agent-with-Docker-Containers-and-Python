"""Normalize generated email body text before sending."""

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


def sanitize_email_body(body: str) -> str:
    """Remove placeholder signatures and tidy trailing closings."""
    text = _PLACEHOLDER_PATTERN.sub("", body)
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
