"""Resolve a Recipient: pinned, then named, then default inbox."""

from __future__ import annotations

from api.myemailer.validation import is_valid_email


def validated_recipient(address: str) -> str:
    if not address or not is_valid_email(address):
        raise ValueError(f"Invalid recipient email: {address}")
    return address.strip()


def resolve_recipient(
    pinned: str | None,
    named: str | None,
    default: str | None,
) -> str:
    recipient = pinned or named or default
    if not recipient:
        raise ValueError("No recipient email configured.")
    return validated_recipient(recipient)
