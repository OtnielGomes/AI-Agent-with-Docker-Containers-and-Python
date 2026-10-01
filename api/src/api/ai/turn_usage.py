"""Usage from model calls that sit inside a tool, outside the supervisor messages."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_messages: ContextVar[list[Any] | None] = ContextVar("turn_usage", default=None)
_research_calls: ContextVar[list[bool] | None] = ContextVar(
    "research_calls", default=None
)


@contextmanager
def collecting_turn_usage() -> Iterator[tuple[list[Any], list[bool]]]:
    messages: list[Any] = []
    calls: list[bool] = []
    message_token = _messages.set(messages)
    call_token = _research_calls.set(calls)
    try:
        yield messages, calls
    finally:
        _messages.reset(message_token)
        _research_calls.reset(call_token)


def note_model_usage(messages: list[Any]) -> None:
    bucket = _messages.get()
    if bucket is not None:
        bucket.extend(messages)


def mark_research_called() -> None:
    bucket = _research_calls.get()
    if bucket is not None:
        bucket.append(True)
