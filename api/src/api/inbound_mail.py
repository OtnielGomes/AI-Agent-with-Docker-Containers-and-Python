"""Shape Inbound emails and Replies. Mailbox I/O stays in the inbox reader."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from email.utils import parseaddr

from api.myemailer.recipient import validated_recipient

INBOUND_LIMIT = 10
INBOUND_DAYS = 7

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
_BREAK = re.compile(r"(?i)<br\s*/?>")
_PARAGRAPH = re.compile(r"(?i)</p\s*>")
_LEADING_RE = re.compile(r"(?i)^re:\s*")
_GREETING = re.compile(
    r"^(ol[aá]|hello|hi|dear|querid[oa]|meu amor|hola|bom dia|boa tarde|boa noite)\b",
    re.IGNORECASE,
)
_CLOSING = re.compile(
    r"^(at[eé] mais!|talk soon!|abraços?|atenciosamente|cordialmente|best regards|sincerely)\b",
    re.IGNORECASE,
)
_PT = re.compile(
    r"[ãõáéíóúâêôç]|(\b(não|voce|você|obrigad|olá|ola|bom dia|att)\b)",
    re.IGNORECASE,
)
_EN = re.compile(
    r"\b(the|and|you|please|thanks|hello|dear|meeting)\b",
    re.IGNORECASE,
)


def reply_subject(subject: str | None) -> str:
    """One leading Re:, or Re: when the Inbound subject is empty."""
    rest = (subject or "").strip()
    while True:
        match = _LEADING_RE.match(rest)
        if match is None:
            break
        rest = rest[match.end() :].strip()
    if not rest:
        return "Re:"
    return f"Re: {rest}"


def split_sender(raw: str | None) -> tuple[str | None, str]:
    name, address = parseaddr(raw or "")
    address = address.strip()
    cleaned = (name or "").strip()
    if not cleaned or cleaned.casefold() == address.casefold() or "@" in cleaned:
        cleaned = None
    return cleaned, address


def html_to_text(raw: str) -> str:
    text = _SCRIPT.sub(" ", raw or "")
    text = _BREAK.sub("\n", text)
    text = _PARAGRAPH.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def plain_body(email: dict) -> str:
    body = email.get("body")
    if isinstance(body, str) and body.strip():
        return body.strip()
    html_body = email.get("html_body")
    if isinstance(html_body, str) and html_body.strip():
        return html_to_text(html_body)
    return ""


def guess_language(text: str) -> str:
    sample = (text or "").strip()
    if len(sample) < 3:
        return "unknown"
    portuguese = len(_PT.findall(sample))
    english = len(_EN.findall(sample))
    if portuguese == 0 and english == 0:
        return "unknown"
    if portuguese > english:
        return "pt"
    if english > portuguese:
        return "en"
    return "unknown"


def reply_language(text: str) -> str:
    guessed = guess_language(text)
    if guessed == "unknown":
        return "pt"
    return guessed


def reply_opening(name: str | None, language: str) -> str:
    cleaned = (name or "").strip()
    if language == "en":
        return f"Hello, {cleaned}," if cleaned else "Hello,"
    return f"Olá, {cleaned}," if cleaned else "Olá,"


def reply_closing(language: str) -> str:
    if language == "en":
        return "Talk soon!"
    return "Até mais!"


def _looks_like_greeting(line: str) -> bool:
    return _GREETING.match(line.strip()) is not None


def _looks_like_closing(line: str) -> bool:
    return _CLOSING.match(line.strip()) is not None


def frame_reply_body(generated: str, opening: str, closing: str) -> str:
    """Put the required Opening and Closing around the answer, without the original mail."""
    lines = (generated or "").splitlines()
    if lines and _looks_like_greeting(lines[0]):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _looks_like_closing(lines[-1]):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    middle = "\n".join(lines).strip()
    if not middle:
        middle = "Here is my reply." if opening.startswith("Hello") else "Segue minha resposta."
    return f"{opening}\n\n{middle}\n\n{closing}"


def to_inbound_item(email: dict) -> dict | None:
    uid = str(email.get("uid") or "").strip()
    if not uid:
        return None
    name, address = split_sender(str(email.get("from") or ""))
    return {
        "id": uid,
        "sender": name or address,
        "address": address,
        "subject": str(email.get("subject") or ""),
        "date": str(email.get("timestamp") or ""),
        "unread": bool(email.get("unread")),
        "body": plain_body(email),
    }


def compose_reply(item: dict, generate: Callable[[str], str]) -> dict:
    """Build one Reply from an Inbound email. The Pinned recipient is not an input."""
    address = validated_recipient(str(item.get("address") or ""))
    sender = str(item.get("sender") or "").strip()
    name = None if not sender or sender.casefold() == address.casefold() else sender
    subject = reply_subject(str(item.get("subject") or ""))
    body = str(item.get("body") or "")
    source = body.strip() or str(item.get("subject") or "")
    language = reply_language(source)
    opening = reply_opening(name, language)
    closing = reply_closing(language)
    language_name = "English" if language == "en" else "Portuguese"
    instruction = (
        f"Write only the middle of a short reply in {language_name}. "
        "Do not include a greeting or a farewell. "
        "Do not quote the original email. Do not mention attachments. "
        f"Subject: {item.get('subject') or ''}\n"
        f"Body: {body.strip() or '(empty; answer from the subject)'}"
    )
    return {
        "subject": subject,
        "body": frame_reply_body(generate(instruction), opening, closing),
        "recipient": address,
    }
