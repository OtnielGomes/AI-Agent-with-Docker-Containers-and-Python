"""Shape Inbound emails and Replies. Mailbox I/O stays in the inbox reader."""

from __future__ import annotations

import re
from collections.abc import Callable
from email.utils import parseaddr
from html.parser import HTMLParser

from api.myemailer.recipient import validated_recipient

INBOUND_LIMIT = 10
INBOUND_DAYS = 7

_TAG = re.compile(r"<[^>]+>")
_LEADING_RE = re.compile(r"(?i)^re:\s*")
_SKIP_TAGS = frozenset({"script", "style", "head", "title", "noscript"})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_INVISIBLE = re.compile(r"[\u00ad\u034f\u200b-\u200d\u2060\ufeff\u180e]")
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all|"
    r"max-height\s*:\s*0(?:px)?|font-size\s*:\s*0(?:px)?|"
    r"opacity\s*:\s*0(?:\.0+)?(?!\d|\.)",
    re.IGNORECASE,
)
_QUOTE_PREFIX = re.compile(r"^(?:> ?)+")
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


class _HTMLTextExtractor(HTMLParser):
    """Collect visible text, with breaks between blocks and cells."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if self._hidden_depth:
            self._hidden_depth += 1
            return
        if name in _SKIP_TAGS:
            self._skip_depth = 1
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if _is_hidden(attr_map):
            self._hidden_depth = 1
            return
        if name == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if self._hidden_depth:
            self._hidden_depth -= 1
            return
        if name in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._hidden_depth:
            return
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _is_hidden(attrs: dict[str, str]) -> bool:
    if "hidden" in attrs or attrs.get("aria-hidden", "").lower() == "true":
        return True
    return _HIDDEN_STYLE.search(attrs.get("style", "")) is not None


def _normalize_text(raw: str, *, strip_quotes: bool) -> str:
    text = _INVISIBLE.sub("", raw)
    text = text.replace("-->", "")
    rows: list[tuple[str, bool]] = []
    for line in text.splitlines():
        content = _QUOTE_PREFIX.sub("", line) if strip_quotes else line
        flowed = bool(content.strip()) and content.endswith((" ", "\t"))
        content = re.sub(r"[^\S\n]+", " ", content).strip()
        rows.append((content, flowed))

    merged: list[str] = []
    previous_flowed = False
    for content, flowed in rows:
        if not content:
            if merged and merged[-1] != "":
                merged.append("")
            previous_flowed = False
            continue
        if merged and merged[-1] and (previous_flowed or content[0].islower()):
            merged[-1] = f"{merged[-1]} {content}"
        else:
            merged.append(content)
        previous_flowed = flowed
    while merged and merged[-1] == "":
        merged.pop()
    return "\n".join(merged).strip()


def html_to_text(raw: str) -> str:
    try:
        extractor = _HTMLTextExtractor()
        extractor.feed(raw or "")
        extractor.close()
        extracted = extractor.text()
    except Exception:
        extracted = _TAG.sub(" ", raw or "")
    return _normalize_text(extracted, strip_quotes=False)


def clean_plain(raw: str) -> str:
    return _normalize_text(raw or "", strip_quotes=True)


def plain_body(email: dict) -> str:
    plain = email.get("body")
    plain_text = clean_plain(plain) if isinstance(plain, str) else ""
    html_body = email.get("html_body")
    if isinstance(html_body, str) and html_body.strip():
        converted = html_to_text(html_body)
        if converted:
            return converted
    return plain_text


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
