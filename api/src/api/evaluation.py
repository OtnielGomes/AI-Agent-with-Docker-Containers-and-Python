"""Score synthetic Evaluation cases. The running app does not call this."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from api.drafts import DRAFT_OPEN, Draft, discard_open_drafts
from api.inbound_mail import guess_language

DEFAULT_INBOX = "inbox@example.com"
SENDER_NAME = "Alex"
PINNED_RECIPIENT = "ana@example.com"

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

_FACT_MARKERS = {
    "the meeting moved to Friday": "sexta",
    "the meeting is on Thursday": "quinta",
    "it mentions the contract": "contrato",
    "it mentions the signature": "assinatura",
    "it describes steps to make a latte": "passos",
    "it mentions milk": "leite",
    "it mentions espresso": "espresso",
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


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    turn_accuracy: int
    failed_checks: tuple[str, ...]
    latency: float
    cost: float


@dataclass(frozen=True)
class ExperimentResult:
    cases: tuple[CaseScore, ...]

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
    scores = tuple(_run_case(case, turn, judge) for case in selected)
    return ExperimentResult(cases=scores)


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


def main(turn: Turn | None = None, judge: Judge | None = None) -> int:
    """Print one line per case and return a failing status when any case scores 0."""
    experiment = run_experiment(
        scripted_turn if turn is None else turn,
        scripted_judge if judge is None else judge,
    )
    for case in experiment.cases:
        print(_format_line(case))
    return 1 if experiment.failed else 0


def _fact_present(fact: str, body: str) -> bool:
    marker = _FACT_MARKERS.get(fact)
    if marker is None:
        return False
    return marker.casefold() in body


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


def _run_case(case: _Case, turn: Turn, judge: Judge) -> CaseScore:
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
            return _case_score(case.id, ("turn",), 0, 0)
        if not isinstance(result, TurnResult):
            return _case_score(case.id, ("turn",), 0, 0)
        return _score_case(case, result, judge)
    finally:
        discard_open_drafts(session)


def _case_session() -> Session:
    engine = create_engine("sqlite://")
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


if __name__ == "__main__":
    raise SystemExit(main())
