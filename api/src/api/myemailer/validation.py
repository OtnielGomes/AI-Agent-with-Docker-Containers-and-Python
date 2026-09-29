"""Email address validation helpers."""

from __future__ import annotations

import re

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(address: str) -> bool:
    """Return True if the string looks like a valid email address."""
    if not address or not address.strip():
        return False
    return bool(_EMAIL_PATTERN.match(address.strip()))
