"""Score synthetic Evaluation cases. The running app does not call this.

The local command can run the chat turn and publish to LangSmith. The API
process does not enable that tracing.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from api.drafts import DRAFT_OPEN, Draft, discard_open_drafts
from api.inbound_mail import guess_language

DEFAULT_INBOX = "inbox@example.com"
SENDER_NAME = "Alex"
PINNED_RECIPIENT = "ana@example.com"
JUDGE_MODEL = "gpt-4o-mini"
DATASET_NAME = "email-assistant-turns"
LANGSMITH_PROJECT = "email-assistant"


@dataclass
class _PublishContext:
    client: Any
    project_name: str
    example_ids: dict[str, Any]
    run_ids: dict[str, Any]


_publish_context: ContextVar[_PublishContext | None] = ContextVar(
    "publish_context", default=None
)

# USD per million tokens: input, cached input, output.
_TOKEN_RATES = {
    "gpt-5-mini": (0.25, 0.025, 2.0),
    "gpt-4o-mini": (0.15, 0.075, 0.6),
}

_CHECK_ORDER = (
    "turn",
    "draft-outcome",
    "recipient",
    "body-language",
    "subject-language",
    "opening",
    "closing",
    "reply-subject",
    "inbound-not-copied",
    "reply-names-recipient",
    "reply-disambiguation",
    "research-called",
    "body-facts",
    "reply-ready",
    "reply-no-extra-offer",
    "reply-not-sent",
    "judge",
)

_ACCEPTED_WORDINGS = {
    "the meeting moved to Friday": ("sexta",),
    "the meeting is on Thursday": ("quinta",),
    "it mentions the contract": ("contrato",),
    "it mentions the signature": ("assinatura", "assinar", "assinado"),
    "it describes steps to make a latte": ("passos", "etapas"),
    "it mentions milk": ("leite",),
    "it mentions espresso": ("espresso", "expresso"),
}


@dataclass(frozen=True)
class InboundEmail:
    id: str
    sender: str
    address: str
    subject: str
    date: str
    body: str
    unread: bool = True


@dataclass(frozen=True)
class OpenDraft:
    id: str
    recipient: str
    subject: str
    body: str


@dataclass(frozen=True)
class ObservedDraft:
    id: str
    recipient: str
    subject: str
    body: str
    kind: str


@dataclass(frozen=True)
class TurnContext:
    case_id: str
    chat_message: str
    pinned_recipient: str | None
    default_inbox: str
    sender_name: str
    inbound_emails: tuple[InboundEmail, ...]
    open_drafts: tuple[OpenDraft, ...]
    session: Session


@dataclass(frozen=True)
class TurnResult:
    assistant_reply: str
    drafts: tuple[ObservedDraft, ...]
    research_called: bool
    latency: float
    cost: float
    outcome: str | None = None
    revision: str | None = None


@dataclass(frozen=True)
class JudgeRequest:
    case_id: str
    fact_propositions: tuple[str, ...]
    outbound_email_body: str | None
    assistant_reply: str
    draft_required: bool


@dataclass(frozen=True)
class JudgeVerdict:
    body_facts: bool
    reply_ready: bool
    reply_no_extra_offer: bool
    reply_not_sent: bool


class _JudgeAnswer(BaseModel):
    body_facts: bool = Field(
        description=(
            "True when every fact proposition is in the outbound email body, "
            "even in other words. True when there are no facts. False when a "
            "fact is missing or there is no body."
        )
    )
    reply_ready: bool = Field(
        description=(
            "When a draft was required, true only if the assistant reply says "
            "the draft is ready. When no draft was required, true only if the "
            "reply does not say a draft is ready."
        )
    )
    reply_no_extra_offer: bool = Field(
        description="False when the assistant reply offers further work. Otherwise true."
    )
    reply_not_sent: bool = Field(
        description=(
            "True when the assistant reply does not claim the email already left. "
            "The sentence 'O rascunho está pronto para ana@example.com.' is true. "
            "'pronto' and 'ready' are true. A claim such as 'foi enviado' is false."
        )
    )


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    turn_accuracy: int
    failed_checks: tuple[str, ...]
    latency: float
    cost: float


@dataclass(frozen=True)
class CaseTrace:
    case_id: str
    chat_message: str
    pinned_recipient: str | None
    inbound_emails: tuple[InboundEmail, ...]
    open_drafts: tuple[OpenDraft, ...]
    assistant_reply: str
    drafts: tuple[ObservedDraft, ...]
    score: CaseScore


@dataclass(frozen=True)
class ExperimentResult:
    cases: tuple[CaseScore, ...]
    traces: tuple[CaseTrace, ...] = ()

    @property
    def failed(self) -> bool:
        return any(case.turn_accuracy == 0 for case in self.cases)


@dataclass(frozen=True)
class _Case:
    id: str
    chat_message: str
    pinned_recipient: str | None
    inbound_emails: tuple[InboundEmail, ...]
    open_drafts: tuple[OpenDraft, ...]
    outcome: str
    expected_recipient: str | None
    expected_opening: str | None
    expected_closing: str | None
    expected_reply_subject: str | None
    forbidden_body: str | None
    disambiguation: tuple[str, ...]
    requires_research: bool
    body_facts: tuple[str, ...]
    expected_draft_id: str | None = None


Turn = Callable[[TurnContext], TurnResult]
Judge = Callable[[JudgeRequest], JudgeVerdict]


def _cases() -> tuple[_Case, ...]:
    revision_id = "00000000-0000-4000-8000-000000000003"
    return (
        _Case(
            id="pin-wins",
            chat_message=(
                "Manda um email para o João dizendo que a reunião passou para sexta."
            ),
            pinned_recipient=PINNED_RECIPIENT,
            inbound_emails=(),
            open_drafts=(),
            outcome="created",
            expected_recipient=PINNED_RECIPIENT,
            expected_opening="Olá, João,",
            expected_closing="Até mais!",
            expected_reply_subject=None,
            forbidden_body=None,
            disambiguation=(),
            requires_research=False,
            body_facts=("the meeting moved to Friday",),
        ),
        _Case(
            id="ambiguous-reply",
            chat_message="Responde o do João.",
            pinned_recipient=None,
            inbound_emails=(
                InboundEmail(
                    id="joao-abril",
                    sender="João Mendes",
                    address="joao@example.com",
                    subject="Fatura de abril",
                    date="2 de outubro de 2026",
                    body="Segue a fatura de abril.",
                ),
                InboundEmail(
                    id="joao-marco",
                    sender="João Mendes",
                    address="joao@example.com",
                    subject="Fatura de março",
                    date="1 de outubro de 2026",
                    body="Segue a fatura de março.",
                ),
            ),
            open_drafts=(),
            outcome="absent",
            expected_recipient=None,
            expected_opening=None,
            expected_closing=None,
            expected_reply_subject=None,
            forbidden_body=None,
            disambiguation=(
                "João Mendes",
                "Fatura de março",
                "Fatura de abril",
                "1 de outubro de 2026",
                "2 de outubro de 2026",
            ),
            requires_research=False,
            body_facts=(),
        ),
        _Case(
            id="revision",
            chat_message="Muda a reunião para quinta.",
            pinned_recipient=PINNED_RECIPIENT,
            inbound_emails=(),
            open_drafts=(
                OpenDraft(
                    id=revision_id,
                    recipient=PINNED_RECIPIENT,
                    subject="Reunião",
                    body=(
                        "Olá, Ana,\n\n"
                        "A reunião está marcada para sexta.\n\n"
                        "Até mais!"
                    ),
                ),
            ),
            outcome="revised",
            expected_recipient=PINNED_RECIPIENT,
            expected_opening="Olá, Ana,",
            expected_closing="Até mais!",
            expected_reply_subject=None,
            forbidden_body=None,
            disambiguation=(),
            requires_research=False,
            body_facts=("the meeting is on Thursday",),
            expected_draft_id=revision_id,
        ),
        _Case(
            id="identified-reply",
            chat_message="Responde o email da Marina sobre o contrato.",
            pinned_recipient=PINNED_RECIPIENT,
            inbound_emails=(
                InboundEmail(
                    id="marina-contrato",
                    sender="Marina Alves",
                    address="marina@example.com",
                    subject="Contrato",
                    date="3 de outubro de 2026",
                    body="O contrato precisa de assinatura até sexta.",
                ),
            ),
            open_drafts=(),
            outcome="created",
            expected_recipient="marina@example.com",
            expected_opening="Olá, Marina,",
            expected_closing="Até mais!",
            expected_reply_subject="Re: Contrato",
            forbidden_body="O contrato precisa de assinatura até sexta.",
            disambiguation=(),
            requires_research=False,
            body_facts=(
                "it mentions the contract",
                "it mentions the signature",
            ),
        ),
        _Case(
            id="research",
            chat_message="Pesquisa os passos de um latte e me manda por email.",
            pinned_recipient=PINNED_RECIPIENT,
            inbound_emails=(),
            open_drafts=(),
            outcome="created",
            expected_recipient=PINNED_RECIPIENT,
            expected_opening="Olá,",
            expected_closing="Até mais!",
            expected_reply_subject=None,
            forbidden_body=None,
            disambiguation=(),
            requires_research=True,
            body_facts=(
                "it describes steps to make a latte",
                "it mentions milk",
                "it mentions espresso",
            ),
        ),
    )


_CANONICAL_CASES = _cases()


def run_experiment(
    turn: Turn,
    judge: Judge,
    *,
    case_ids: Sequence[str] | None = None,
) -> ExperimentResult:
    """Score each Evaluation case once. Latency and cost do not decide the pass."""
    selected = _select_cases(case_ids)
    traces = tuple(_run_case(case, turn, judge) for case in selected)
    return ExperimentResult(
        cases=tuple(trace.score for trace in traces),
        traces=traces,
    )


def scripted_turn(context: TurnContext) -> TurnResult:
    """Deterministic turn used by the local command and the regular check."""
    ready = f"O rascunho está pronto para {PINNED_RECIPIENT}."
    results = {
        "pin-wins": TurnResult(
            assistant_reply=ready,
            drafts=(
                ObservedDraft(
                    id="00000000-0000-4000-8000-000000000010",
                    recipient=PINNED_RECIPIENT,
                    subject="Reunião",
                    body="Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!",
                    kind="created",
                ),
            ),
            research_called=False,
            latency=0.2,
            cost=0.01,
        ),
        "ambiguous-reply": TurnResult(
            assistant_reply=(
                "Qual email do João Mendes? "
                "Fatura de abril em 2 de outubro de 2026, "
                "ou Fatura de março em 1 de outubro de 2026?"
            ),
            drafts=(),
            research_called=False,
            latency=0.2,
            cost=0.01,
        ),
        "revision": TurnResult(
            assistant_reply=ready,
            drafts=(
                ObservedDraft(
                    id="00000000-0000-4000-8000-000000000003",
                    recipient=PINNED_RECIPIENT,
                    subject="Reunião",
                    body=(
                        "Olá, Ana,\n\n"
                        "A reunião está marcada para quinta.\n\n"
                        "Até mais!"
                    ),
                    kind="revised",
                ),
            ),
            research_called=False,
            latency=0.2,
            cost=0.01,
        ),
        "identified-reply": TurnResult(
            assistant_reply="O rascunho está pronto para marina@example.com.",
            drafts=(
                ObservedDraft(
                    id="00000000-0000-4000-8000-000000000021",
                    recipient="marina@example.com",
                    subject="Re: Contrato",
                    body=(
                        "Olá, Marina,\n\n"
                        "O contrato segue para assinatura.\n\n"
                        "Até mais!"
                    ),
                    kind="created",
                ),
            ),
            research_called=False,
            latency=0.2,
            cost=0.01,
        ),
        "research": TurnResult(
            assistant_reply=ready,
            drafts=(
                ObservedDraft(
                    id="00000000-0000-4000-8000-000000000030",
                    recipient=PINNED_RECIPIENT,
                    subject="Latte",
                    body=(
                        "Olá,\n\n"
                        "Passos de um latte: aqueça o leite e extraia o espresso.\n\n"
                        "Até mais!"
                    ),
                    kind="created",
                ),
            ),
            research_called=True,
            latency=0.2,
            cost=0.01,
        ),
    }
    try:
        return results[context.case_id]
    except KeyError as exc:
        raise ValueError(f"Unknown Evaluation case: {context.case_id}") from exc


def scripted_judge(request: JudgeRequest) -> JudgeVerdict:
    """Judge facts and the Assistant reply without calling a model."""
    body = (request.outbound_email_body or "").casefold()
    facts_ok = all(_fact_present(fact, body) for fact in request.fact_propositions)
    reply = request.assistant_reply.casefold()
    says_ready = "pronto" in reply or "pronta" in reply
    if request.draft_required:
        reply_ready = says_ready
    else:
        reply_ready = not says_ready
    offers_more = "posso ajudar" in reply or "mais alguma" in reply
    claims_sent = (
        "foi enviado" in reply or "já enviei" in reply or "ja enviei" in reply
    )
    return JudgeVerdict(
        body_facts=facts_ok,
        reply_ready=reply_ready,
        reply_no_extra_offer=not offers_more,
        reply_not_sent=not claims_sent,
    )


def chat_turn(
    context: TurnContext,
    *,
    supervisor_factory: Callable[[], Any] | None = None,
) -> TurnResult:
    """One chat turn for an Evaluation case.

    The supervisor is built inside the synthetic inbox identity, so the prompt
    sees Alex and ``inbox@example.com``. Draft and inbox tools use the case
    store. The call does not Confirm and does not write a Chat message.
    """
    publishing = _publish_context.get()
    if publishing is None:
        return _invoke_chat_turn(context, supervisor_factory)
    from langsmith import trace

    inputs = _context_inputs(context)
    with trace(
        context.case_id,
        run_type="chain",
        inputs=inputs,
        client=publishing.client,
        project_name=publishing.project_name,
        reference_example_id=publishing.example_ids.get(context.case_id),
    ) as run:
        publishing.run_ids[context.case_id] = run.id
        result = _invoke_chat_turn(context, supervisor_factory)
        run.end(outputs=_turn_outputs(result))
        return result


def _invoke_chat_turn(
    context: TurnContext,
    supervisor_factory: Callable[[], Any] | None,
) -> TurnResult:
    from api.ai.turn_usage import collecting_turn_usage
    from api.chat.turn import SupervisorTurnError, run_shared_turn

    factory = _default_supervisor if supervisor_factory is None else supervisor_factory
    with _synthetic_identity():
        with collecting_turn_usage() as (extra_usage, research_calls):
            try:
                outcome = run_shared_turn(
                    chat_message=context.chat_message,
                    pinned_recipient=context.pinned_recipient,
                    open_drafts=context.open_drafts,
                    inbound_emails=context.inbound_emails,
                    session=context.session,
                    default_inbox=context.default_inbox,
                    sender_name=context.sender_name,
                    supervisor_factory=factory,
                )
            except SupervisorTurnError as exc:
                raise ValueError("Supervisor returned no result") from exc
    drafts = _observed_drafts(context.open_drafts, outcome.drafts)
    return TurnResult(
        assistant_reply=outcome.assistant_reply,
        drafts=drafts,
        research_called=bool(research_calls) or _research_called(outcome.messages),
        latency=outcome.latency,
        cost=_messages_cost(outcome.messages) + _messages_cost(extra_usage),
        outcome=outcome.outcome,
        revision=outcome.revision,
    )


def score_with_chat_turn() -> int:
    """Score the five cases with the chat turn and the scripted judge."""
    return main(chat_turn, scripted_judge)


def _default_supervisor() -> Any:
    from api.ai.agents import get_supervisor

    return get_supervisor()


@contextmanager
def _synthetic_identity() -> Iterator[None]:
    keys = ("EMAIL_ADDRESS", "EMAIL_SENDER_NAME")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["EMAIL_ADDRESS"] = DEFAULT_INBOX
    os.environ["EMAIL_SENDER_NAME"] = SENDER_NAME
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _observed_drafts(
    open_drafts: Sequence[OpenDraft],
    created: Sequence[Any],
) -> tuple[ObservedDraft, ...]:
    seeded = {draft.id for draft in open_drafts}
    observed: list[ObservedDraft] = []
    for draft in created:
        draft_id = str(draft.id)
        kind = "revised" if draft_id in seeded else "created"
        observed.append(
            ObservedDraft(
                id=draft_id,
                recipient=draft.recipient,
                subject=draft.subject,
                body=draft.body,
                kind=kind,
            )
        )
    return tuple(observed)


def _research_called(messages: Sequence[Any]) -> bool:
    for message in messages:
        if getattr(message, "name", None) == "research_email":
            return True
        for call in getattr(message, "tool_calls", None) or []:
            if isinstance(call, dict) and call.get("name") == "research_email":
                return True
            if getattr(call, "name", None) == "research_email":
                return True
    return False


def _messages_cost(messages: Sequence[Any]) -> float:
    return sum(_message_cost(message) for message in messages)


def _message_cost(message: Any) -> float:
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        return 0.0
    rate = _rate_for(_model_name(message))
    if rate is None:
        return 0.0
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    details = usage.get("input_token_details") or {}
    cached = 0
    if isinstance(details, dict):
        cached = int(details.get("cache_read") or details.get("cached_tokens") or 0)
    cached = min(max(cached, 0), input_tokens)
    fresh = input_tokens - cached
    input_rate, cached_rate, output_rate = rate
    return (
        fresh * input_rate + cached * cached_rate + output_tokens * output_rate
    ) / 1_000_000


def _model_name(message: Any) -> str:
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        name = meta.get("model_name") or meta.get("model") or ""
        if name:
            return str(name)
    return os.environ.get("OPENAI_MODEL_NAME") or ""


def _rate_for(model_name: str) -> tuple[float, float, float] | None:
    for key in sorted(_TOKEN_RATES, key=len, reverse=True):
        if model_name.startswith(key):
            return _TOKEN_RATES[key]
    return None


def model_judge(
    *,
    answer: Callable[[JudgeRequest], Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> Judge:
    """Judge with gpt-4o-mini, using the assistant's API key and base URL.

    A caller may pass ``answer`` or ``client_factory`` so the regular check
    never calls the model. The assistant's model setting is ignored.
    The client opens on the first case, so a failure scores that case and
    the other cases still run.
    """
    if answer is None:
        answer = _live_answer(client_factory)

    def judge(request: JudgeRequest) -> JudgeVerdict:
        verdict = _verdict_from(answer(request))
        if verdict is None:
            raise ValueError("Unreadable judge answer")
        verdict = _settle_sent_claim(verdict, request.assistant_reply)
        return _settle_body_facts(verdict, request)

    return judge


def score_with_model_judge() -> int:
    """Score the five cases with the scripted turn and the model judge."""
    return main(judge=model_judge())


def main(turn: Turn | None = None, judge: Judge | None = None) -> int:
    """Print one line per case and return a failing status when any case scores 0."""
    experiment = run_experiment(
        scripted_turn if turn is None else turn,
        scripted_judge if judge is None else judge,
    )
    for case in experiment.cases:
        print(_format_line(case))
    return 1 if experiment.failed else 0


_VERDICT_FIELDS = (
    "body_facts",
    "reply_ready",
    "reply_no_extra_offer",
    "reply_not_sent",
)

_JUDGE_INSTRUCTIONS = (
    "Judge one email assistant turn. "
    "body_facts is true only when every fact proposition is stated in the "
    "outbound email body, including when the wording differs. "
    "It is true when there are no fact propositions, and false when a required "
    "fact is missing or there is no body. "
    "When a draft was required, reply_ready is true only if the assistant reply "
    "says the draft is ready. "
    "When no draft was required, reply_ready is true only if the reply does not "
    "say a draft is ready. "
    "reply_no_extra_offer is false when the reply offers further work. "
    "reply_not_sent is false only when the assistant reply claims the email "
    "already left, for example 'foi enviado' or 'I sent it'. "
    "Saying the draft is ready, naming the recipient, or saying it will be "
    "sent after the human confirms is not a sent claim. "
    "'pronto' and 'ready' are not sent claims."
)


def _live_answer(client_factory: Callable[..., Any] | None):
    structured = None

    def answer(request: JudgeRequest):
        nonlocal structured
        if structured is None:
            factory = client_factory or _chat_openai
            client = factory(**_judge_client_params())
            structured = client.with_structured_output(_JudgeAnswer)
        return structured.invoke(
            [
                ("system", _JUDGE_INSTRUCTIONS),
                ("human", _judge_case_text(request)),
            ]
        )

    return answer


def _chat_openai(**kwargs):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(**kwargs)


def _judge_client_params() -> dict[str, str]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise NotImplementedError("OPENAI_API_KEY is required")
    params = {"model": JUDGE_MODEL, "api_key": api_key}
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    if base_url:
        params["base_url"] = base_url
    return params


_SENT_CLAIMS = ("foi enviado", "já enviei", "ja enviei")


def _settle_sent_claim(verdict: JudgeVerdict, reply: str) -> JudgeVerdict:
    """A ready sentence is not a sent claim. A sent claim stays a failure."""
    folded = (reply or "").strip().casefold()
    if any(phrase in folded for phrase in _SENT_CLAIMS):
        sent_ok = False
    elif folded.startswith("o rascunho está pronto para ") or folded.startswith(
        "the draft is ready for "
    ):
        sent_ok = True
    else:
        return verdict
    if verdict.reply_not_sent == sent_ok:
        return verdict
    return replace(verdict, reply_not_sent=sent_ok)


def _settle_body_facts(verdict: JudgeVerdict, request: JudgeRequest) -> JudgeVerdict:
    """A fact whose Accepted wording is in the body counts, even if the model says no."""
    body = (request.outbound_email_body or "").casefold()
    if not request.fact_propositions:
        return verdict
    if not all(_fact_present(fact, body) for fact in request.fact_propositions):
        return verdict
    if verdict.body_facts:
        return verdict
    return replace(verdict, body_facts=True)


def _judge_case_text(request: JudgeRequest) -> str:
    facts = "\n".join(f"- {fact}" for fact in request.fact_propositions)
    if request.outbound_email_body is None:
        body = "(none)"
    else:
        body = request.outbound_email_body
    required = "yes" if request.draft_required else "no"
    return (
        f"fact propositions:\n{facts}\n\n"
        f"draft required: {required}\n\n"
        f"outbound email body:\n{body}\n\n"
        f"assistant reply:\n{request.assistant_reply}"
    )


def _verdict_from(raw: Any) -> JudgeVerdict | None:
    values = {name: getattr(raw, name, None) for name in _VERDICT_FIELDS}
    if any(type(value) is not bool for value in values.values()):
        return None
    return JudgeVerdict(**values)


def _fact_present(fact: str, body: str) -> bool:
    wordings = _ACCEPTED_WORDINGS.get(fact)
    if not wordings:
        return False
    return any(wording.casefold() in body for wording in wordings)


def _select_cases(case_ids: Sequence[str] | None) -> tuple[_Case, ...]:
    if case_ids is None:
        return _CANONICAL_CASES
    by_id = {case.id: case for case in _CANONICAL_CASES}
    selected: list[_Case] = []
    for case_id in case_ids:
        try:
            selected.append(by_id[case_id])
        except KeyError as exc:
            raise ValueError(f"Unknown Evaluation case: {case_id}") from exc
    return tuple(selected)


def _run_case(case: _Case, turn: Turn, judge: Judge) -> CaseTrace:
    session = _case_session()
    try:
        _seed_open_drafts(session, case.open_drafts)
        context = TurnContext(
            case_id=case.id,
            chat_message=case.chat_message,
            pinned_recipient=case.pinned_recipient,
            default_inbox=DEFAULT_INBOX,
            sender_name=SENDER_NAME,
            inbound_emails=case.inbound_emails,
            open_drafts=case.open_drafts,
            session=session,
        )
        try:
            result = turn(context)
        except Exception:
            return _trace(case, "", (), _case_score(case.id, ("turn",), 0, 0))
        if not isinstance(result, TurnResult):
            return _trace(case, "", (), _case_score(case.id, ("turn",), 0, 0))
        score = _score_case(case, result, judge)
        return _trace(case, result.assistant_reply, result.drafts, score)
    finally:
        session.rollback()
        discard_open_drafts(session)


def _trace(
    case: _Case,
    reply: str,
    drafts: Sequence[ObservedDraft],
    score: CaseScore,
) -> CaseTrace:
    return CaseTrace(
        case_id=case.id,
        chat_message=case.chat_message,
        pinned_recipient=case.pinned_recipient,
        inbound_emails=case.inbound_emails,
        open_drafts=case.open_drafts,
        assistant_reply=reply,
        drafts=tuple(drafts),
        score=score,
    )


def _case_session() -> Session:
    """One in-memory store, shared by the thread that runs the Draft tools."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[Draft.__table__])
    return Session(engine)


def _seed_open_drafts(session: Session, drafts: tuple[OpenDraft, ...]) -> None:
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for index, draft in enumerate(drafts):
        session.add(
            Draft(
                id=uuid.UUID(draft.id),
                subject=draft.subject,
                body=draft.body,
                recipient=draft.recipient,
                state=DRAFT_OPEN,
                created_at=base + timedelta(seconds=index),
            )
        )
    session.commit()


def _score_case(case: _Case, result: TurnResult, judge: Judge) -> CaseScore:
    failed = _structural_checks(case, result)
    request = JudgeRequest(
        case_id=case.id,
        fact_propositions=case.body_facts,
        outbound_email_body=_body_for_judge(result),
        assistant_reply=result.assistant_reply,
        draft_required=case.outcome != "absent",
    )
    try:
        verdict = judge(request)
    except Exception:
        failed.append("judge")
        return _case_score(case.id, failed, result.latency, result.cost)
    if not isinstance(verdict, JudgeVerdict):
        failed.append("judge")
        return _case_score(case.id, failed, result.latency, result.cost)
    _judge_checks(case, verdict, failed)
    return _case_score(case.id, failed, result.latency, result.cost)


def _body_for_judge(result: TurnResult) -> str | None:
    if len(result.drafts) != 1:
        return None
    return result.drafts[0].body


def _structural_checks(case: _Case, result: TurnResult) -> list[str]:
    failed: list[str] = []
    draft = _candidate_draft(case, result.drafts)
    if _outcome_failed(case, result.drafts):
        failed.append("draft-outcome")
    if draft is not None:
        _draft_checks(case, draft, failed)
    if case.outcome != "absent":
        named = draft.recipient if draft is not None else case.expected_recipient
        if named and named not in result.assistant_reply:
            failed.append("reply-names-recipient")
    if case.disambiguation and any(
        term not in result.assistant_reply for term in case.disambiguation
    ):
        failed.append("reply-disambiguation")
    if case.requires_research and not result.research_called:
        failed.append("research-called")
    return failed


def _outcome_failed(case: _Case, drafts: tuple[ObservedDraft, ...]) -> bool:
    if case.outcome == "absent":
        return bool(drafts)
    return _candidate_draft(case, drafts) is None


def _candidate_draft(
    case: _Case, drafts: tuple[ObservedDraft, ...]
) -> ObservedDraft | None:
    if case.outcome == "absent" or len(drafts) != 1:
        return None
    draft = drafts[0]
    if case.outcome == "created" and draft.kind == "created":
        return draft
    if (
        case.outcome == "revised"
        and draft.kind == "revised"
        and draft.id == case.expected_draft_id
    ):
        return draft
    return None


def _draft_checks(case: _Case, draft: ObservedDraft, failed: list[str]) -> None:
    if draft.recipient != case.expected_recipient:
        failed.append("recipient")
    if guess_language(draft.body) != "pt":
        failed.append("body-language")
    if guess_language(draft.subject) == "en":
        failed.append("subject-language")
    lines = _nonempty_lines(draft.body)
    opening = lines[0] if lines else ""
    closing = lines[-1] if lines else ""
    if opening != case.expected_opening:
        failed.append("opening")
    if closing != case.expected_closing:
        failed.append("closing")
    if (
        case.expected_reply_subject is not None
        and draft.subject != case.expected_reply_subject
    ):
        failed.append("reply-subject")
    if case.forbidden_body and case.forbidden_body in draft.body:
        failed.append("inbound-not-copied")


def _judge_checks(case: _Case, verdict: JudgeVerdict, failed: list[str]) -> None:
    if case.body_facts and not verdict.body_facts:
        failed.append("body-facts")
    if not verdict.reply_ready:
        failed.append("reply-ready")
    if not verdict.reply_no_extra_offer:
        failed.append("reply-no-extra-offer")
    if not verdict.reply_not_sent:
        failed.append("reply-not-sent")


def _nonempty_lines(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.strip()]


def _case_score(
    case_id: str,
    failed: Sequence[str],
    latency: float,
    cost: float,
) -> CaseScore:
    ordered = tuple(check for check in _CHECK_ORDER if check in failed)
    accuracy = 0 if ordered else 1
    return CaseScore(
        case_id=case_id,
        turn_accuracy=accuracy,
        failed_checks=ordered,
        latency=latency,
        cost=cost,
    )


def _format_line(case: CaseScore) -> str:
    failed = ",".join(case.failed_checks) if case.failed_checks else "-"
    return (
        f"{case.case_id} {case.turn_accuracy} {failed} "
        f"{_format_metric(case.latency)} {_format_metric(case.cost)}"
    )


def _format_metric(value: float) -> str:
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"


def langsmith_client() -> Any:
    """LangSmith client for the local command. Tracing stays off."""
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        raise NotImplementedError("LANGSMITH_API_KEY is required")
    from langsmith import Client

    return Client(api_key=api_key)


def publish_experiment(experiment: ExperimentResult, client: Any) -> str:
    """Upsert the cases into the dataset and open one new Experiment."""
    dataset = _upsert_dataset(client)
    example_ids = _upsert_examples(client, dataset.id, experiment.traces)
    project_name = _experiment_name()
    project = client.create_project(
        project_name=project_name,
        reference_dataset_id=dataset.id,
        description="Synthetic Evaluation cases",
        metadata={"langsmith_project": _langsmith_project()},
    )
    for trace in experiment.traces:
        _publish_trace(
            client, project_name, example_ids[trace.case_id], trace, project.id
        )
    return project_name


def run_local_experiment(
    turn: Turn | None = None,
    judge: Judge | None = None,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> int:
    """Chat turn, model judge, then one LangSmith Experiment."""
    chosen_turn = chat_turn if turn is None else turn
    chosen_judge = model_judge() if judge is None else judge
    factory = langsmith_client if client_factory is None else client_factory
    if chosen_turn is chat_turn:
        return _run_traced_experiment(factory(), chosen_judge)
    experiment = run_experiment(chosen_turn, chosen_judge)
    for case in experiment.cases:
        print(_format_line(case))
    publish_experiment(experiment, factory())
    return 1 if experiment.failed else 0


def _run_traced_experiment(client: Any, judge: Judge) -> int:
    """Trace each chat turn, then attach the score. The judge stays outside."""
    dataset = _upsert_dataset(client)
    example_ids = _upsert_examples(client, dataset.id, _CANONICAL_CASES)
    project_name = _experiment_name()
    project = client.create_project(
        project_name=project_name,
        reference_dataset_id=dataset.id,
        description="Synthetic Evaluation cases",
        metadata={"langsmith_project": _langsmith_project()},
    )
    publishing = _PublishContext(
        client=client,
        project_name=project_name,
        example_ids=example_ids,
        run_ids={},
    )
    token = _publish_context.set(publishing)
    try:
        experiment = run_experiment(chat_turn, judge)
    finally:
        _publish_context.reset(token)
    for case in experiment.cases:
        print(_format_line(case))
    for trace in experiment.traces:
        run_id = publishing.run_ids.get(trace.case_id)
        if run_id is None:
            _publish_trace(
                client, project_name, example_ids[trace.case_id], trace, project.id
            )
            continue
        client.update_run(run_id, outputs=_trace_outputs(trace))
        _feedback(client, run_id, trace.score, project.id)
    return 1 if experiment.failed else 0


def local_command(argv: Sequence[str] | None = None) -> int:
    """Entry for ``api/experiment.py``.

    ``--scripted-judge`` scores the chat turn with the scripted judge and
    does not call LangSmith.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--scripted-judge" in args:
        return score_with_chat_turn()
    return run_local_experiment()


def _upsert_dataset(client: Any) -> Any:
    if client.has_dataset(dataset_name=DATASET_NAME):
        return client.read_dataset(dataset_name=DATASET_NAME)
    return client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Synthetic Evaluation cases from git",
    )


def _upsert_examples(client: Any, dataset_id: Any, cases: Sequence[Any]) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    for example in client.list_examples(dataset_id=dataset_id):
        case_id = _example_case_id(example)
        if case_id and case_id not in existing:
            existing[case_id] = example
    ids: dict[str, Any] = {}
    for case in cases:
        case_id = _case_key(case)
        inputs = _context_inputs(case)
        metadata = {"case_id": case_id}
        current = existing.get(case_id)
        if current is None:
            created = client.create_example(
                inputs=inputs,
                dataset_id=dataset_id,
                metadata=metadata,
            )
            ids[case_id] = created.id
        else:
            client.update_example(current.id, inputs=inputs, metadata=metadata)
            ids[case_id] = current.id
    return ids


def _publish_trace(
    client: Any,
    project_name: str,
    example_id: Any,
    trace: CaseTrace,
    experiment_id: Any,
) -> None:
    run_id = uuid.uuid4()
    started = datetime.now(timezone.utc)
    ended = started + timedelta(seconds=trace.score.latency)
    client.create_run(
        name=trace.case_id,
        inputs=_trace_inputs(trace),
        run_type="chain",
        project_name=project_name,
        outputs=_trace_outputs(trace),
        reference_example_id=example_id,
        id=run_id,
        start_time=started,
        end_time=ended,
    )
    _feedback(client, run_id, trace.score, experiment_id)


def _feedback(client: Any, run_id: Any, score: CaseScore, experiment_id: Any) -> None:
    client.create_feedback(
        run_id, "turn_accuracy", score=score.turn_accuracy, session_id=experiment_id
    )
    client.create_feedback(
        run_id, "latency", score=score.latency, session_id=experiment_id
    )
    client.create_feedback(run_id, "cost", score=score.cost, session_id=experiment_id)
    client.create_feedback(
        run_id,
        "failed_checks",
        score=0 if score.failed_checks else 1,
        comment=",".join(score.failed_checks),
        session_id=experiment_id,
    )


def _case_key(case: Any) -> str:
    if getattr(case, "case_id", None):
        return str(case.case_id)
    return str(case.id)


def _context_inputs(case: Any) -> dict[str, Any]:
    from api.chat.turn_message import inbound_record

    return {
        "case_id": _case_key(case),
        "chat_message": case.chat_message,
        "pinned_recipient": case.pinned_recipient,
        "default_inbox": DEFAULT_INBOX,
        "sender_name": SENDER_NAME,
        "inbound_emails": [inbound_record(item) for item in case.inbound_emails],
        "open_drafts": [_open_draft_input(item) for item in case.open_drafts],
    }


def _turn_outputs(result: TurnResult) -> dict[str, Any]:
    return {
        "assistant_reply": result.assistant_reply,
        "drafts": [_observed_input(item) for item in result.drafts],
        "latency": result.latency,
        "cost": result.cost,
    }


def _trace_inputs(trace: CaseTrace) -> dict[str, Any]:
    return _context_inputs(trace)


def _trace_outputs(trace: CaseTrace) -> dict[str, Any]:
    score = trace.score
    return {
        "assistant_reply": trace.assistant_reply,
        "drafts": [_observed_input(item) for item in trace.drafts],
        "turn_accuracy": score.turn_accuracy,
        "failed_checks": list(score.failed_checks),
        "latency": score.latency,
        "cost": score.cost,
    }


def _open_draft_input(draft: OpenDraft) -> dict[str, str]:
    return {
        "id": draft.id,
        "recipient": draft.recipient,
        "subject": draft.subject,
        "body": draft.body,
    }


def _observed_input(draft: ObservedDraft) -> dict[str, str]:
    return {
        "id": draft.id,
        "recipient": draft.recipient,
        "subject": draft.subject,
        "body": draft.body,
        "kind": draft.kind,
    }


def _example_case_id(example: Any) -> str | None:
    metadata = getattr(example, "metadata", None) or {}
    if isinstance(metadata, dict) and metadata.get("case_id"):
        return str(metadata["case_id"])
    inputs = getattr(example, "inputs", None) or {}
    if isinstance(inputs, dict) and inputs.get("case_id"):
        return str(inputs["case_id"])
    return None


def _langsmith_project() -> str:
    configured = (os.environ.get("LANGSMITH_PROJECT") or "").strip()
    return configured or LANGSMITH_PROJECT


def _experiment_name() -> str:
    return f"{_langsmith_project()}-{uuid.uuid4().hex[:12]}"


if __name__ == "__main__":
    raise SystemExit(main())
