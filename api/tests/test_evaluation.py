"""Score Evaluation cases through the Experiment, with a scripted turn and judge."""

import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, create_engine

from api.drafts import DRAFT_OPEN, Draft, create_open_draft, list_open_drafts
from api.evaluation import (
    JudgeRequest,
    JudgeVerdict,
    TurnContext,
    main,
    model_judge,
    score_with_model_judge,
    run_experiment,
    scripted_judge,
    scripted_turn,
)

PASSING_JUDGE = JudgeVerdict(
    body_facts=True,
    reply_ready=True,
    reply_no_extra_offer=True,
    reply_not_sent=True,
)

_CASE_ORDER = (
    "pin-wins",
    "ambiguous-reply",
    "revision",
    "identified-reply",
    "research",
)


def _judge_pass(_request):
    return PASSING_JUDGE


_IDLE_SESSION = Session(create_engine("sqlite://"))


def _passing(case_id: str):
    """The command's scripted turn for one case, without running the case store."""
    return scripted_turn(
        TurnContext(
            case_id=case_id,
            chat_message="",
            pinned_recipient=None,
            default_inbox="inbox@example.com",
            sender_name="Alex",
            inbound_emails=(),
            open_drafts=(),
            session=_IDLE_SESSION,
        )
    )


def _turn_for(case_id: str, result):
    def turn(context):
        if context.case_id == case_id:
            return result
        return scripted_turn(context)

    return turn


def _score_break(case_id: str, result, judge=_judge_pass):
    experiment = run_experiment(
        _turn_for(case_id, result),
        judge,
        case_ids=(case_id,),
    )
    return experiment.cases[0]


def test_scripted_run_scores_the_five_cases_in_order():
    experiment = run_experiment(scripted_turn, scripted_judge)

    assert tuple(case.case_id for case in experiment.cases) == _CASE_ORDER
    assert tuple(case.turn_accuracy for case in experiment.cases) == (1, 1, 1, 1, 1)
    assert all(case.failed_checks == () for case in experiment.cases)
    assert experiment.failed is False


def test_latency_and_cost_do_not_decide_turn_accuracy():
    def turn(context):
        result = scripted_turn(context)
        if context.case_id == "pin-wins":
            return replace(result, latency=10000, cost=99)
        return replace(result, research_called=False, latency=0, cost=0)

    experiment = run_experiment(
        turn, _judge_pass, case_ids=("pin-wins", "research")
    )

    assert experiment.cases[0].turn_accuracy == 1
    assert experiment.cases[0].latency == 10000
    assert experiment.cases[0].cost == 99
    assert experiment.cases[0].failed_checks == ()
    assert experiment.cases[1].turn_accuracy == 0
    assert experiment.cases[1].failed_checks == ("research-called",)
    assert experiment.cases[1].latency == 0
    assert experiment.cases[1].cost == 0


def test_every_case_runs_when_an_earlier_turn_scores_zero():
    calls = []

    def turn(context):
        calls.append(context.case_id)
        if context.case_id == "pin-wins":
            raise RuntimeError("turn failed")
        return scripted_turn(context)

    experiment = run_experiment(turn, _judge_pass)

    assert calls == list(_CASE_ORDER)
    assert experiment.failed is True
    assert experiment.cases[0].turn_accuracy == 0
    assert experiment.cases[0].failed_checks == ("turn",)
    assert experiment.cases[0].latency == 0
    assert experiment.cases[0].cost == 0
    assert experiment.cases[1].turn_accuracy == 1


def test_a_judge_that_raises_scores_judge_and_the_run_continues():
    calls = []

    def judge(request):
        calls.append(request.case_id)
        if request.case_id == "pin-wins":
            raise RuntimeError("judge failed")
        return PASSING_JUDGE

    experiment = run_experiment(scripted_turn, judge)

    assert calls == list(_CASE_ORDER)
    assert experiment.cases[0].turn_accuracy == 0
    assert experiment.cases[0].failed_checks == ("judge",)
    assert experiment.cases[1].turn_accuracy == 1
    assert experiment.failed is True


def test_turn_receives_the_case_mail_newest_first_and_drafts_oldest_first():
    seen = {}
    stored_ids: dict[str, tuple[str, ...]] = {}

    def turn(context):
        seen[context.case_id] = context
        stored_ids[context.case_id] = tuple(
            str(draft.id) for draft in list_open_drafts(context.session)
        )
        return scripted_turn(context)

    run_experiment(turn, _judge_pass)

    pin = seen["pin-wins"]
    assert pin.chat_message == (
        "Manda um email para o João dizendo que a reunião passou para sexta."
    )
    assert pin.pinned_recipient == "ana@example.com"
    assert pin.default_inbox == "inbox@example.com"
    assert pin.sender_name == "Alex"
    assert pin.inbound_emails == ()
    assert pin.open_drafts == ()

    ambiguous = seen["ambiguous-reply"]
    assert ambiguous.pinned_recipient is None
    assert ambiguous.chat_message == "Responde o do João."
    assert tuple(email.id for email in ambiguous.inbound_emails) == (
        "joao-abril",
        "joao-marco",
    )
    abril, marco = ambiguous.inbound_emails
    assert abril.sender == "João Mendes"
    assert abril.address == "joao@example.com"
    assert abril.subject == "Fatura de abril"
    assert abril.date == "2 de outubro de 2026"
    assert abril.unread is True
    assert marco.sender == "João Mendes"
    assert marco.subject == "Fatura de março"
    assert marco.date == "1 de outubro de 2026"
    assert marco.unread is True
    assert ambiguous.open_drafts == ()

    revision = seen["revision"]
    assert revision.pinned_recipient == "ana@example.com"
    assert revision.chat_message == "Muda a reunião para quinta."
    assert len(revision.open_drafts) == 1
    seeded = revision.open_drafts[0]
    assert seeded.id == "00000000-0000-4000-8000-000000000003"
    assert seeded.recipient == "ana@example.com"
    assert seeded.subject == "Reunião"
    assert _nonempty(seeded.body) == [
        "Olá, Ana,",
        "A reunião está marcada para sexta.",
        "Até mais!",
    ]
    assert stored_ids["revision"] == ("00000000-0000-4000-8000-000000000003",)
    assert stored_ids["pin-wins"] == ()
    assert stored_ids["ambiguous-reply"] == ()

    reply = seen["identified-reply"]
    assert reply.inbound_emails[0].id == "marina-contrato"
    assert reply.inbound_emails[0].sender == "Marina Alves"
    assert reply.inbound_emails[0].address == "marina@example.com"
    assert reply.inbound_emails[0].subject == "Contrato"
    assert reply.inbound_emails[0].date == "3 de outubro de 2026"
    assert reply.inbound_emails[0].body == (
        "O contrato precisa de assinatura até sexta."
    )
    assert reply.pinned_recipient == "ana@example.com"

    research = seen["research"]
    assert research.chat_message == (
        "Pesquisa os passos de um latte e me manda por email."
    )
    assert research.inbound_emails == ()
    assert research.open_drafts == ()
    assert research.pinned_recipient == "ana@example.com"


def test_draft_opened_in_the_case_store_is_gone_when_the_case_ends():
    held = {}

    def turn(context):
        held["session"] = context.session
        create_open_draft(
            context.session,
            subject="Nota",
            body="Olá,\n\nSegue.\n\nAté mais!\nAlex",
            pinned=context.pinned_recipient,
            named=None,
            default=context.default_inbox,
            sender_name=context.sender_name,
        )
        return scripted_turn(context)

    run_experiment(turn, _judge_pass, case_ids=("pin-wins",))

    assert list_open_drafts(held["session"]) == []


def test_a_draft_saved_on_another_thread_stays_in_the_case_store():
    seen = {}

    def turn(context):
        box = {}

        def save():
            try:
                create_open_draft(
                    context.session,
                    subject="Nota",
                    body="Olá,\n\nSegue.\n\nAté mais!\nAlex",
                    pinned=context.pinned_recipient,
                    named=None,
                    default=context.default_inbox,
                    sender_name=context.sender_name,
                )
            except Exception as exc:
                box["error"] = exc

        worker = threading.Thread(target=save)
        worker.start()
        worker.join()
        if "error" in box:
            raise box["error"]
        seen["open"] = [draft.recipient for draft in list_open_drafts(context.session)]
        seen["session"] = context.session
        return scripted_turn(context)

    run_experiment(turn, _judge_pass, case_ids=("pin-wins",))

    assert seen["open"] == ["ana@example.com"]
    assert list_open_drafts(seen["session"]) == []


def test_a_failed_flush_still_scores_the_turn_and_runs_the_next_case():
    def turn(context):
        if context.case_id == "pin-wins":
            context.session.connection().exec_driver_sql(
                "CREATE TRIGGER abort_draft BEFORE INSERT ON draft "
                "BEGIN SELECT RAISE(ABORT, 'flush failed'); END"
            )
            context.session.add(
                Draft(
                    subject="Nota",
                    body="Olá,",
                    recipient="ana@example.com",
                    state=DRAFT_OPEN,
                )
            )
            context.session.commit()
        return scripted_turn(context)

    experiment = run_experiment(
        turn, _judge_pass, case_ids=("pin-wins", "ambiguous-reply")
    )

    assert experiment.cases[0].failed_checks == ("turn",)
    assert experiment.cases[1].turn_accuracy == 1


def test_case_store_is_not_the_application_database():
    def turn(context):
        url = str(context.session.get_bind().url)
        assert url == "sqlite://"
        tables = set(inspect(context.session.get_bind()).get_table_names())
        assert "chatmessage" not in tables
        assert list_open_drafts(context.session) == []
        return scripted_turn(context)

    run_experiment(turn, _judge_pass, case_ids=("pin-wins",))


def test_judge_sees_facts_body_and_reply():
    seen = {}

    def judge(request):
        seen[request.case_id] = request
        return PASSING_JUDGE

    run_experiment(
        scripted_turn,
        judge,
        case_ids=("pin-wins", "ambiguous-reply"),
    )

    pin = seen["pin-wins"]
    assert pin.fact_propositions == ("the meeting moved to Friday",)
    assert pin.outbound_email_body == (
        "Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!"
    )
    assert pin.assistant_reply == "O rascunho está pronto para ana@example.com."
    assert pin.draft_required is True

    ambiguous = seen["ambiguous-reply"]
    assert ambiguous.fact_propositions == ()
    assert ambiguous.outbound_email_body is None
    assert ambiguous.draft_required is False


def test_failed_checks_follow_decision_order():
    result = _passing("pin-wins")
    draft = replace(
        result.drafts[0],
        recipient="other@example.com",
        subject="The meeting",
        body="Olá,\n\nA reunião passou para sexta.\n\nAbraços",
    )
    score = _score_break(
        "pin-wins",
        replace(
            result,
            drafts=(draft,),
            assistant_reply="O rascunho está pronto para other@example.com.",
        ),
    )

    assert score.turn_accuracy == 0
    assert score.failed_checks == (
        "recipient",
        "subject-language",
        "opening",
        "closing",
    )


@pytest.mark.parametrize(
    ("case_id", "mutate", "failed"),
    [
        (
            "pin-wins",
            lambda result: replace(result, drafts=()),
            ("draft-outcome",),
        ),
        (
            "pin-wins",
            lambda result: replace(
                result,
                drafts=(
                    replace(result.drafts[0], recipient="other@example.com"),
                ),
                assistant_reply="O rascunho está pronto para other@example.com.",
            ),
            ("recipient",),
        ),
        (
            "pin-wins",
            lambda result: replace(
                result,
                drafts=(
                    replace(
                        result.drafts[0],
                        body=(
                            "Olá, João,\n\n"
                            "Please send the meeting and the notes you and the team need.\n\n"
                            "Até mais!"
                        ),
                    ),
                ),
            ),
            ("body-language",),
        ),
        (
            "pin-wins",
            lambda result: replace(
                result,
                drafts=(replace(result.drafts[0], subject="The meeting"),),
            ),
            ("subject-language",),
        ),
        (
            "revision",
            lambda result: replace(
                result,
                drafts=(replace(result.drafts[0], subject="Nota"),),
            ),
            (),
        ),
        (
            "pin-wins",
            lambda result: replace(
                result,
                drafts=(
                    replace(
                        result.drafts[0],
                        body="Olá,\n\nA reunião passou para sexta.\n\nAté mais!",
                    ),
                ),
            ),
            ("opening",),
        ),
        (
            "pin-wins",
            lambda result: replace(
                result,
                drafts=(
                    replace(
                        result.drafts[0],
                        body="Olá, João,\n\nA reunião passou para sexta.\n\nAbraços",
                    ),
                ),
            ),
            ("closing",),
        ),
        (
            "identified-reply",
            lambda result: replace(
                result,
                drafts=(replace(result.drafts[0], subject="Contrato"),),
            ),
            ("reply-subject",),
        ),
        (
            "identified-reply",
            lambda result: replace(
                result,
                drafts=(
                    replace(
                        result.drafts[0],
                        body=(
                            "Olá, Marina,\n\n"
                            "O contrato precisa de assinatura até sexta.\n\n"
                            "Até mais!"
                        ),
                    ),
                ),
            ),
            ("inbound-not-copied",),
        ),
        (
            "pin-wins",
            lambda result: replace(
                result,
                assistant_reply="O rascunho está pronto.",
            ),
            ("reply-names-recipient",),
        ),
        (
            "ambiguous-reply",
            lambda result: replace(
                result,
                assistant_reply="Qual email do João Mendes?",
            ),
            ("reply-disambiguation",),
        ),
        (
            "research",
            lambda result: replace(result, research_called=False),
            ("research-called",),
        ),
        (
            "revision",
            lambda result: replace(
                result,
                drafts=(
                    replace(
                        result.drafts[0],
                        id="00000000-0000-4000-8000-000000000099",
                        kind="created",
                    ),
                ),
            ),
            ("draft-outcome",),
        ),
    ],
)
def test_a_turn_that_breaks_one_check_lists_that_check(case_id, mutate, failed):
    score = _score_break(case_id, mutate(_passing(case_id)))

    assert score.failed_checks == failed
    assert score.turn_accuracy == (0 if failed else 1)


@pytest.mark.parametrize(
    ("case_id", "verdict", "failed"),
    [
        (
            "pin-wins",
            JudgeVerdict(False, True, True, True),
            ("body-facts",),
        ),
        (
            "pin-wins",
            JudgeVerdict(True, False, True, True),
            ("reply-ready",),
        ),
        (
            "ambiguous-reply",
            JudgeVerdict(True, False, True, True),
            ("reply-ready",),
        ),
        (
            "pin-wins",
            JudgeVerdict(True, True, False, True),
            ("reply-no-extra-offer",),
        ),
        (
            "pin-wins",
            JudgeVerdict(True, True, True, False),
            ("reply-not-sent",),
        ),
        (
            "ambiguous-reply",
            JudgeVerdict(False, True, True, True),
            (),
        ),
    ],
)
def test_a_judge_check_is_listed_only_when_it_applies(case_id, verdict, failed):
    score = _score_break(
        case_id,
        _passing(case_id),
        judge=lambda _request: verdict,
    )

    assert score.failed_checks == failed
    assert score.turn_accuracy == (0 if failed else 1)


def _with_body(case_id: str, body: str):
    result = _passing(case_id)
    return replace(result, drafts=(replace(result.drafts[0], body=body),))


@pytest.mark.parametrize(
    ("case_id", "body"),
    [
        (
            "research",
            "Olá,\n\n"
            "Etapas de um latte: aqueça o leite e extraia o espresso.\n\n"
            "Até mais!",
        ),
        (
            "research",
            "Olá,\n\n"
            "Passos de um latte: aqueça o leite e extraia o expresso.\n\n"
            "Até mais!",
        ),
        (
            "research",
            "Olá,\n\n"
            "Etapas de um latte: aqueça o leite e extraia o expresso.\n\n"
            "Até mais!",
        ),
        (
            "identified-reply",
            "Olá, Marina,\n\nO contrato segue para assinar.\n\nAté mais!",
        ),
        (
            "identified-reply",
            "Olá, Marina,\n\nO contrato segue assinado.\n\nAté mais!",
        ),
        (
            "pin-wins",
            "Olá, João,\n\nA reunião passou para sexta-feira.\n\nAté mais!",
        ),
        (
            "revision",
            "Olá, Ana,\n\nA reunião está marcada para quinta-feira.\n\nAté mais!",
        ),
        (
            "research",
            "Olá,\n\n"
            "Etapas de um latte: aqueça o Leite e extraia o Espresso.\n\n"
            "Até mais!",
        ),
        (
            "research",
            "Olá,\n\n"
            "ETAPAS de um latte: aqueça o LEITE e extraia o EXPRESSO.\n\n"
            "Até mais!",
        ),
        (
            "research",
            "Olá,\n\n"
            "Os passos para o latte usam leite e espresso no preparo.\n\n"
            "Até mais!",
        ),
    ],
)
def test_scripted_judge_accepts_one_wording_of_each_required_fact(case_id, body):
    score = _score_break(case_id, _with_body(case_id, body), judge=scripted_judge)

    assert score.turn_accuracy == 1
    assert score.failed_checks == ()


@pytest.mark.parametrize(
    ("case_id", "body"),
    [
        (
            "research",
            "Olá,\n\nAqueça o leite e extraia o espresso.\n\nAté mais!",
        ),
        (
            "research",
            "Olá,\n\nPassos de um latte: extraia o espresso.\n\nAté mais!",
        ),
        (
            "research",
            "Olá,\n\nPassos de um latte: aqueça o leite.\n\nAté mais!",
        ),
        (
            "research",
            "Olá,\n\nAqueça o leite.\n\nAté mais!",
        ),
        (
            "identified-reply",
            "Olá, Marina,\n\nO contrato segue para assiná-lo.\n\nAté mais!",
        ),
    ],
)
def test_scripted_judge_lists_body_facts_when_a_fact_has_no_accepted_wording(
    case_id, body
):
    score = _score_break(case_id, _with_body(case_id, body), judge=scripted_judge)

    assert score.turn_accuracy == 0
    assert score.failed_checks == ("body-facts",)


def test_scripted_judge_fails_a_body_that_omits_the_friday_move():
    result = _passing("pin-wins")
    broken = replace(
        result,
        drafts=(
            replace(
                result.drafts[0],
                body="Olá, João,\n\nA reunião continua na quarta.\n\nAté mais!",
            ),
        ),
    )
    score = _score_break("pin-wins", broken, judge=scripted_judge)

    assert score.failed_checks == ("body-facts",)


def test_scripted_judge_fails_when_a_required_reply_does_not_say_ready():
    result = _passing("pin-wins")
    broken = replace(
        result,
        assistant_reply="Segue o email para ana@example.com.",
    )
    score = _score_break("pin-wins", broken, judge=scripted_judge)

    assert score.failed_checks == ("reply-ready",)


def test_scripted_judge_fails_when_a_reply_without_a_draft_says_one_is_ready():
    result = _passing("ambiguous-reply")
    broken = replace(
        result,
        assistant_reply=(
            "O rascunho está pronto. Qual email do João Mendes? "
            "Fatura de abril em 2 de outubro de 2026, "
            "ou Fatura de março em 1 de outubro de 2026?"
        ),
    )
    score = _score_break("ambiguous-reply", broken, judge=scripted_judge)

    assert score.failed_checks == ("reply-ready",)


def test_scripted_judge_fails_an_offer_of_further_work_and_a_sent_claim():
    offer = replace(
        _passing("pin-wins"),
        assistant_reply=(
            "O rascunho está pronto para ana@example.com. Posso ajudar com mais alguma coisa?"
        ),
    )
    sent = replace(
        _passing("pin-wins"),
        assistant_reply=(
            "O rascunho está pronto para ana@example.com. O email foi enviado."
        ),
    )

    assert _score_break("pin-wins", offer, judge=scripted_judge).failed_checks == (
        "reply-no-extra-offer",
    )
    assert _score_break("pin-wins", sent, judge=scripted_judge).failed_checks == (
        "reply-not-sent",
    )


def _model_answer(**overrides):
    fields = {
        "body_facts": True,
        "reply_ready": True,
        "reply_no_extra_offer": True,
        "reply_not_sent": True,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _recording_chat_factory(seen):
    class FakeChat:
        def with_structured_output(self, schema):
            seen["schema"] = schema
            return self

        def invoke(self, messages):
            seen["messages"] = messages
            return _model_answer()

    def factory(**kwargs):
        seen["kwargs"] = kwargs
        return FakeChat()

    return factory


def test_model_judge_passes_a_fact_stated_in_different_words():
    result = _passing("pin-wins")
    paraphrased = replace(
        result,
        drafts=(
            replace(
                result.drafts[0],
                body=(
                    "Olá, João,\n\n"
                    "A reunião foi adiada para o último dia útil da semana.\n\n"
                    "Até mais!"
                ),
            ),
        ),
    )
    seen = {}

    def complete(request):
        seen["request"] = request
        return _model_answer()

    score = _score_break(
        "pin-wins",
        paraphrased,
        judge=model_judge(answer=complete),
    )

    assert seen["request"].fact_propositions == ("the meeting moved to Friday",)
    assert "último dia útil" in seen["request"].outbound_email_body
    assert seen["request"].assistant_reply == result.assistant_reply
    assert seen["request"].draft_required is True
    assert score.failed_checks == ()
    assert score.turn_accuracy == 1
    assert _score_break(
        "pin-wins", paraphrased, judge=scripted_judge
    ).failed_checks == ("body-facts",)


def test_model_judge_fails_body_facts_when_the_model_says_the_fact_is_missing():
    def complete(_request):
        return _model_answer(body_facts=False)

    result = _passing("pin-wins")
    missing = replace(
        result,
        drafts=(
            replace(
                result.drafts[0],
                body="Olá, João,\n\nA reunião mudou de dia.\n\nAté mais!",
            ),
        ),
    )
    score = _score_break(
        "pin-wins",
        missing,
        judge=model_judge(answer=complete),
    )

    assert score.failed_checks == ("body-facts",)
    assert score.turn_accuracy == 0


def test_model_judge_accepts_a_fact_whose_accepted_wording_is_in_the_body():
    def complete(_request):
        return _model_answer(body_facts=False)

    score = _score_break(
        "pin-wins",
        _passing("pin-wins"),
        judge=model_judge(answer=complete),
    )

    assert score.failed_checks == ()
    assert score.turn_accuracy == 1


def test_model_judge_does_not_treat_a_ready_sentence_as_sent():
    def complete(_request):
        return _model_answer(reply_not_sent=False)

    score = _score_break(
        "pin-wins",
        _passing("pin-wins"),
        judge=model_judge(answer=complete),
    )

    assert score.failed_checks == ()
    assert score.turn_accuracy == 1


def test_model_judge_still_fails_when_the_reply_says_the_email_was_sent():
    def complete(_request):
        return _model_answer(reply_not_sent=True)

    sent = replace(
        _passing("pin-wins"),
        assistant_reply=(
            "O rascunho está pronto para ana@example.com. O email foi enviado."
        ),
    )
    score = _score_break("pin-wins", sent, judge=model_judge(answer=complete))

    assert score.failed_checks == ("reply-not-sent",)
    assert score.turn_accuracy == 0


@pytest.mark.parametrize(
    ("case_id", "flag", "failed"),
    [
        ("pin-wins", "reply_ready", ("reply-ready",)),
        ("ambiguous-reply", "reply_ready", ("reply-ready",)),
        ("pin-wins", "reply_no_extra_offer", ("reply-no-extra-offer",)),
        ("pin-wins", "reply_not_sent", ("reply-not-sent",)),
    ],
)
def test_model_judge_reports_the_reply_check_the_model_fails(case_id, flag, failed):
    def complete(_request):
        return _model_answer(**{flag: False})

    result = _passing(case_id)
    if flag == "reply_not_sent":
        result = replace(
            result,
            assistant_reply="Enviei o rascunho para ana@example.com.",
        )
    score = _score_break(
        case_id,
        result,
        judge=model_judge(answer=complete),
    )

    assert score.failed_checks == failed
    assert score.turn_accuracy == 0


def test_unreadable_model_answer_scores_judge_and_the_run_continues():
    def complete(request):
        if request.case_id == "pin-wins":
            return "maybe"
        return _model_answer()

    experiment = run_experiment(
        scripted_turn,
        model_judge(answer=complete),
        case_ids=("pin-wins", "ambiguous-reply"),
    )

    assert experiment.cases[0].turn_accuracy == 0
    assert experiment.cases[0].failed_checks == ("judge",)
    assert experiment.cases[1].turn_accuracy == 1
    assert experiment.failed is True


def test_missing_judge_credentials_score_judge_and_the_run_continues(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    experiment = run_experiment(
        scripted_turn,
        model_judge(),
        case_ids=("pin-wins", "ambiguous-reply"),
    )

    assert experiment.cases[0].turn_accuracy == 0
    assert experiment.cases[0].failed_checks == ("judge",)
    assert experiment.cases[1].turn_accuracy == 0
    assert experiment.cases[1].failed_checks == ("judge",)
    assert experiment.failed is True


def test_model_judge_rejects_a_non_boolean_answer():
    def complete(_request):
        return _model_answer(body_facts="yes")

    score = _score_break(
        "pin-wins",
        _passing("pin-wins"),
        judge=model_judge(answer=complete),
    )

    assert score.failed_checks == ("judge",)
    assert score.turn_accuracy == 0


def test_command_judge_uses_gpt_4o_mini_on_the_assistant_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-assistant")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://assistant.example/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "gpt-5-mini")
    seen = {}

    experiment = run_experiment(
        scripted_turn,
        model_judge(client_factory=_recording_chat_factory(seen)),
        case_ids=("pin-wins",),
    )

    assert experiment.cases[0].turn_accuracy == 1
    assert seen["kwargs"] == {
        "model": "gpt-4o-mini",
        "api_key": "sk-assistant",
        "base_url": "http://assistant.example/v1",
    }
    assert set(seen["schema"].model_fields) == {
        "body_facts",
        "reply_ready",
        "reply_no_extra_offer",
        "reply_not_sent",
    }
    text = _message_text(seen["messages"])
    assert "the meeting moved to Friday" in text
    assert "A reunião passou para sexta." in text
    assert "O rascunho está pronto para ana@example.com." in text
    assert "already left" in text
    assert "'pronto' and 'ready' are not sent claims." in text
    description = seen["schema"].model_fields["reply_not_sent"].description
    assert "does not claim the email already left" in description


def test_command_judge_omits_base_url_when_the_assistant_has_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-assistant")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_MODEL_NAME", "gpt-5-mini")
    seen = {}

    model_judge(client_factory=_recording_chat_factory(seen))(
        JudgeRequest(
            case_id="research",
            fact_propositions=(
                "it describes steps to make a latte",
                "it mentions milk",
                "it mentions espresso",
            ),
            outbound_email_body=None,
            assistant_reply="O rascunho está pronto para ana@example.com.",
            draft_required=True,
        )
    )

    assert seen["kwargs"] == {
        "model": "gpt-4o-mini",
        "api_key": "sk-assistant",
    }


def test_local_command_asks_the_model_judge(monkeypatch, capsys):
    def fake_judge(_request):
        return PASSING_JUDGE

    monkeypatch.setattr("api.evaluation.model_judge", lambda: fake_judge)

    assert score_with_model_judge() == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines] == ["1", "1", "1", "1", "1"]


def test_regular_check_scores_with_the_scripted_judge(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise AssertionError("regular check called the model judge")

    monkeypatch.setattr("api.evaluation.model_judge", boom)

    assert main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines] == ["1", "1", "1", "1", "1"]


def test_command_prints_one_line_per_case_and_exits_success_when_all_pass(capsys):
    code = main()
    captured = capsys.readouterr()

    assert code == 0
    lines = captured.out.splitlines()
    assert [line.split()[0] for line in lines] == list(_CASE_ORDER)
    assert [line.split()[1] for line in lines] == ["1", "1", "1", "1", "1"]
    assert all(" - " in line for line in lines)


def test_judge_latency_and_cost_stay_outside_the_turn():
    def turn(context):
        result = scripted_turn(context)
        return replace(result, latency=4.5, cost=0.33)

    def judge(request):
        return PASSING_JUDGE

    experiment = run_experiment(turn, judge, case_ids=("pin-wins",))
    score = experiment.cases[0]

    assert score.turn_accuracy == 1
    assert score.latency == 4.5
    assert score.cost == 0.33


def test_unreadable_judge_answer_scores_judge_and_the_run_continues():
    calls = []

    def judge(request):
        calls.append(request.case_id)
        if request.case_id == "pin-wins":
            return "not a verdict"
        return PASSING_JUDGE

    experiment = run_experiment(scripted_turn, judge)

    assert calls == list(_CASE_ORDER)
    assert experiment.cases[0].turn_accuracy == 0
    assert experiment.cases[0].failed_checks == ("judge",)
    assert experiment.cases[1].turn_accuracy == 1
    assert experiment.failed is True


def test_command_exits_failure_after_printing_every_case(capsys):
    def turn(context):
        if context.case_id == "revision":
            raise RuntimeError("turn failed")
        result = scripted_turn(context)
        return replace(result, latency=1.5, cost=0.25)

    code = main(turn, _judge_pass)
    lines = capsys.readouterr().out.splitlines()

    assert code == 1
    assert len(lines) == 5
    assert lines[0] == "pin-wins 1 - 1.5 0.25"
    assert lines[2] == "revision 0 turn 0 0"
    assert lines[4].split()[1] == "1"


def _nonempty(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.strip()]


def _message_text(messages) -> str:
    parts = []
    for message in messages:
        if isinstance(message, tuple):
            parts.append(str(message[1]))
        else:
            parts.append(str(getattr(message, "content", message)))
    return "\n".join(parts)
