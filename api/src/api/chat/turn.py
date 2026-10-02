"""One chat turn for the live route and the Experiment."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session


_OPENING_LINE = re.compile(
    r"^(ol[aá]|hello|hi|dear|querid[oa]|meu amor)\b",
    re.IGNORECASE,
)
_CLOSING_LINE = re.compile(
    r"^(at[eé] mais!|talk soon!|abraços!?|atenciosamente|cordialmente|best regards|sincerely)\.?$",
    re.IGNORECASE,
)


class SupervisorTurnError(Exception):
    """The supervisor returned no messages for this turn."""


@dataclass(frozen=True)
class SharedTurn:
    assistant_reply: str
    drafts: tuple[Any, ...]
    reply_targets: dict[str, str]
    messages: tuple[Any, ...]
    latency: float
    outcome: str | None = None
    revision: str | None = None


def run_shared_turn(
    *,
    chat_message: str,
    pinned_recipient: str | None,
    open_drafts: Sequence[Any],
    inbound_emails: Sequence[Any],
    session: Session,
    default_inbox: str | None,
    sender_name: str | None,
    supervisor_factory: Callable[[], Any],
) -> SharedTurn:
    """Run one turn. It does not Confirm, call SMTP, or read the real mailbox.

    The caller saves the Chat message when the Session should show it.
    """
    from api.ai.messages import extract_assistant_reply
    from api.ai.tools import CaseTools, use_case_tools
    from api.ai.turn_usage import collecting_research_drafts
    from api.chat.turn_message import (
        asks_for_new_outbound,
        disambiguation_reply,
        recipient_question,
        reply_names_recipient,
        with_open_drafts,
    )
    from api.drafts import collecting_created_drafts, collecting_reply_targets

    inbound_question = disambiguation_reply(chat_message, inbound_emails)
    clear_send = inbound_question is not None and _clear_new_send(chat_message)
    if inbound_question is not None and not clear_send:
        return SharedTurn(inbound_question, (), {}, (), 0.0)
    question = None if clear_send else inbound_question
    if question is None and not clear_send:
        question = recipient_question(
            chat_message, pinned_recipient, default_inbox
        )
    if question is not None:
        return _question_turn(
            question,
            chat_message,
            open_drafts,
            session=session,
            sender_name=sender_name,
        )

    revised = _revision_turn(
        chat_message,
        open_drafts,
        session=session,
        sender_name=sender_name,
    )
    if revised is not None:
        return revised

    supervisor = supervisor_factory()
    message = with_open_drafts(
        chat_message, open_drafts, inbound_emails, pinned_recipient
    )
    config: dict[str, Any] = {}
    if pinned_recipient:
        config["configurable"] = {"to_email": pinned_recipient}
    binding = CaseTools(
        session=session,
        default_inbox=default_inbox,
        sender_name=sender_name,
        inbound_emails=tuple(inbound_emails),
    )
    with use_case_tools(binding):
        with collecting_reply_targets() as reply_targets:
            with collecting_created_drafts() as drafts:
                with collecting_research_drafts() as researched:
                    started = time.perf_counter()
                    result = supervisor.invoke(
                        {"messages": [{"role": "user", "content": message}]},
                        config=config,
                    )
                    latency = time.perf_counter() - started
                    _store_research_draft(
                        chat_message,
                        result,
                        drafts,
                        researched,
                        session=session,
                        pinned_recipient=pinned_recipient,
                        default_inbox=default_inbox,
                        sender_name=sender_name,
                    )
                    _apply_subject_revision(
                        chat_message,
                        open_drafts,
                        drafts,
                        session=session,
                        sender_name=sender_name,
                    )
    if not isinstance(result, dict) or not result.get("messages"):
        raise SupervisorTurnError("Supervisor returned no result")
    messages = result["messages"]
    reply = extract_assistant_reply(list(messages))
    if clear_send and inbound_question is not None:
        kept = _without_replies(drafts, reply_targets, session)
        return SharedTurn(
            inbound_question,
            tuple(kept),
            {},
            tuple(messages),
            latency,
            outcome="question",
        )
    finished = _finish_combined(
        chat_message,
        open_drafts,
        drafts,
        reply,
        reply_targets,
        messages,
        latency,
    )
    if finished is not None:
        return finished
    if len(drafts) == 1:
        reply = reply_names_recipient(reply, drafts[0].recipient, chat_message)
    outcome = None
    if asks_for_new_outbound(chat_message) and not drafts:
        outcome = "creation failed"
    return SharedTurn(
        assistant_reply=reply,
        drafts=tuple(drafts),
        reply_targets=dict(reply_targets),
        messages=tuple(messages),
        latency=latency,
        outcome=outcome,
    )


def _clear_new_send(chat_message: str) -> bool:
    from api.chat.turn_message import asks_for_new_outbound, named_recipient

    return asks_for_new_outbound(chat_message) and named_recipient(chat_message) is not None


def _without_replies(
    drafts: list[Any],
    reply_targets: dict[str, str],
    session: Session,
) -> list[Any]:
    from api.drafts import discard_draft

    kept: list[Any] = []
    for draft in drafts:
        if str(draft.id) not in reply_targets:
            kept.append(draft)
            continue
        discard_draft(session, uuid.UUID(str(draft.id)))
    return kept


def _question_turn(
    question: str,
    chat_message: str,
    open_drafts: Sequence[Any],
    *,
    session: Session,
    sender_name: str | None,
) -> SharedTurn:
    """A Recipient question stays, and a Revision with one target still lands."""
    from api.chat.turn_message import asks_for_both
    from api.drafts import revise_open_draft

    shown: tuple[Any, ...] = ()
    revision = None
    outcome = None
    if asks_for_both(chat_message):
        outcome = "question"
        if len(open_drafts) == 1:
            current = open_drafts[0]
            draft = revise_open_draft(
                session,
                uuid.UUID(str(current.id)),
                subject=requested_subject_for(chat_message),
                body=current.body,
                sender_name=sender_name,
            )
            shown = (draft,)
        else:
            revision = "failed"
    return SharedTurn(
        question, shown, {}, (), 0.0, outcome=outcome, revision=revision
    )


def requested_subject_for(chat_message: str) -> str:
    from api.chat.turn_message import requested_subject

    subject = requested_subject(chat_message)
    if subject is None:
        raise ValueError("Revision has no subject")
    return subject


def _apply_subject_revision(
    chat_message: str,
    open_drafts: Sequence[Any],
    drafts: list[Any],
    *,
    session: Session,
    sender_name: str | None,
) -> None:
    from api.chat.turn_message import asks_for_both, requested_subject
    from api.drafts import revise_open_draft

    if not asks_for_both(chat_message) or len(open_drafts) != 1:
        return
    subject = requested_subject(chat_message)
    if subject is None:
        return
    current = open_drafts[0]
    if any(str(draft.id) == str(current.id) for draft in drafts):
        return
    revise_open_draft(
        session,
        uuid.UUID(str(current.id)),
        subject=subject,
        body=current.body,
        sender_name=sender_name,
    )


def _finish_combined(
    chat_message: str,
    open_drafts: Sequence[Any],
    drafts: list[Any],
    reply: str,
    reply_targets: dict[str, str],
    messages: Sequence[Any],
    latency: float,
) -> SharedTurn | None:
    from api.chat.turn_message import asks_for_both
    from api.inbound_mail import reply_language

    if not asks_for_both(chat_message):
        return None
    seeded = {str(item.id) for item in open_drafts}
    created = [draft for draft in drafts if str(draft.id) not in seeded]
    revised = [draft for draft in drafts if str(draft.id) in seeded]
    if created and revised:
        recipient = created[0].recipient
        if reply_language(chat_message) == "en":
            reply = (
                f"The draft is ready for {recipient}, and the other was updated."
            )
        else:
            reply = (
                f"O rascunho está pronto para {recipient}, e o outro foi atualizado."
            )
        shown = tuple(drafts)
        outcome = "ready"
    elif revised:
        reply = ""
        shown = tuple(revised)
        outcome = "creation failed"
    elif created:
        reply = ""
        shown = tuple(created)
        outcome = "revision failed"
    else:
        reply = ""
        shown = ()
        outcome = "both failed"
    return SharedTurn(
        assistant_reply=reply,
        drafts=shown,
        reply_targets=dict(reply_targets),
        messages=tuple(messages),
        latency=latency,
        outcome=outcome,
    )


def _revision_turn(
    chat_message: str,
    open_drafts: Sequence[Any],
    *,
    session: Session,
    sender_name: str | None,
) -> SharedTurn | None:
    """A Revision is not a failed creation, even when it says manda or enviar."""
    from api.chat.turn_message import (
        is_revision_request,
        reply_names_recipient,
        requested_subject,
    )
    from api.drafts import revise_open_draft
    from api.inbound_mail import reply_language

    if not is_revision_request(chat_message):
        return None
    english = reply_language(chat_message) == "en"
    if not open_drafts:
        reply = (
            "There is nothing to revise."
            if english
            else "Não há rascunho para atualizar."
        )
        return SharedTurn(reply, (), {}, (), 0.0)
    if len(open_drafts) > 1:
        return SharedTurn(_which_draft(open_drafts, english), (), {}, (), 0.0)
    subject = requested_subject(chat_message)
    if subject is None:
        return None
    draft = revise_open_draft(
        session,
        uuid.UUID(str(open_drafts[0].id)),
        subject=subject,
        body=open_drafts[0].body,
        sender_name=sender_name,
    )
    reply = reply_names_recipient("", draft.recipient, chat_message)
    return SharedTurn(reply, (draft,), {}, (), 0.0)


def _which_draft(open_drafts: Sequence[Any], english: bool) -> str:
    if english:
        listed = ", or ".join(
            f"{draft.subject} for {draft.recipient}" for draft in open_drafts
        )
        return f"Which draft? {listed}."
    listed = ", ou ".join(
        f"{draft.subject} para {draft.recipient}" for draft in open_drafts
    )
    return f"Qual rascunho? {listed}."


def _with_opening_and_closing(body: str, chat_message: str) -> str:
    """A research body becomes an Outbound email body, with one Opening and Closing."""
    from api.inbound_mail import reply_closing, reply_language, reply_opening

    language = reply_language(chat_message)
    opening = reply_opening(None, language)
    closing = reply_closing(language)
    nonempty = [line.strip() for line in body.splitlines() if line.strip()]
    has_opening = bool(nonempty) and _OPENING_LINE.match(nonempty[0]) is not None
    has_closing = bool(nonempty) and _CLOSING_LINE.match(nonempty[-1]) is not None
    if has_opening and has_closing:
        return body
    middle = body.strip()
    if has_opening:
        return f"{middle}\n\n{closing}"
    if has_closing:
        return f"{opening}\n\n{middle}"
    return f"{opening}\n\n{middle}\n\n{closing}"


def _store_research_draft(
    chat_message: str,
    result: Any,
    drafts: list[Any],
    researched: Sequence[tuple[str, str]],
    *,
    session: Session,
    pinned_recipient: str | None,
    default_inbox: str | None,
    sender_name: str | None,
) -> None:
    """Store one Draft from research when the turn asked for it and opened none."""
    from api.chat.turn_message import named_recipient, researched_outbound
    from api.drafts import create_open_draft

    if drafts or not isinstance(result, dict):
        return
    messages = result.get("messages") or []
    drafted = researched_outbound(chat_message, messages, researched)
    if drafted is None:
        return
    subject, body = drafted
    body = _with_opening_and_closing(body, chat_message)
    create_open_draft(
        session,
        subject=subject,
        body=body,
        pinned=pinned_recipient,
        named=named_recipient(chat_message),
        default=default_inbox,
        sender_name=sender_name,
    )
