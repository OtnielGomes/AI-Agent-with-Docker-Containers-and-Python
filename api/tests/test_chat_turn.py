"""The Experiment's chat turn uses the real Draft and inbox tools."""

import os
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from api.drafts import Draft, list_open_drafts
from api.ai.tools import (
    get_recent_emails,
    get_unread_emails,
    research_email,
    revise_email_draft,
    send_me_email,
)
from api.evaluation import (
    InboundEmail,
    TurnContext,
    chat_turn,
    run_experiment,
    scripted_judge,
)

_READY = "O rascunho está pronto para ana@example.com."
_MARINA_READY = "O rascunho está pronto para marina@example.com."
_AMBIGUOUS = (
    "Qual email do João Mendes? "
    "Fatura de abril em 2 de outubro de 2026, "
    "ou Fatura de março em 1 de outubro de 2026?"
)


class _Supervisor:
    def __init__(self, invoke):
        self._invoke = invoke

    def invoke(self, data, config=None):
        return self._invoke(data, config)


def _reply(text, *, usage=None, model=None, tool_calls=None, name=None):
    return SimpleNamespace(
        content=text,
        usage_metadata=usage,
        response_metadata={"model_name": model} if model else {},
        tool_calls=tool_calls or [],
        name=name,
    )


def _messages(*messages):
    return {"messages": list(messages)}


def _closed_mailbox(*_args, **_kwargs):
    raise AssertionError("read the real mailbox")


def _closed_confirm(*_args, **_kwargs):
    raise AssertionError("confirmed a Draft")


def _closed_database(*_args, **_kwargs):
    raise AssertionError("opened the application database")


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[Draft.__table__])
    return Session(engine)


def _context(**overrides):
    fields = {
        "case_id": "pin-wins",
        "chat_message": "Oi",
        "pinned_recipient": "ana@example.com",
        "default_inbox": "inbox@example.com",
        "sender_name": "Alex",
        "inbound_emails": (),
        "open_drafts": (),
        "session": _session(),
    }
    fields.update(overrides)
    return TurnContext(**fields)


def _run(case_id, invoke, monkeypatch):
    monkeypatch.setattr("api.ai.tools.read_inbox", _closed_mailbox)
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    held = {}

    def turn(context):
        names = []
        original = context.session.add

        def spy(obj, _original=original):
            names.append(type(obj).__name__)
            return _original(obj)

        context.session.add = spy
        held["names"] = names
        held["session"] = context.session
        return chat_turn(context, supervisor_factory=lambda: _Supervisor(invoke))

    experiment = run_experiment(turn, scripted_judge, case_ids=(case_id,))
    held["score"] = experiment.cases[0]
    held["trace"] = experiment.traces[0]
    return held


def test_pin_wins_uses_the_real_draft_and_leaves_the_case_store(monkeypatch):
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    import api.db

    monkeypatch.setattr(api.db.engine, "connect", _closed_database)

    def invoke(data, config=None):
        assert "none" in data["messages"][0]["content"]
        assert config["configurable"]["to_email"] == "ana@example.com"
        send_me_email.invoke(
            {
                "subject": "Reunião",
                "content": (
                    "Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!\nAlex"
                ),
            },
            config=config,
        )
        return _messages(_reply(_READY))

    held = _run("pin-wins", invoke, monkeypatch)

    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()
    assert "ChatMessage" not in held["names"]
    assert "Draft" in held["names"]
    assert list_open_drafts(held["session"]) == []
    assert "Alex" not in held["trace"].drafts[0].body


def test_draft_without_a_pin_uses_the_synthetic_inbox_and_strips_alex(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "private-inbox@gmail.com")
    monkeypatch.setenv("EMAIL_SENDER_NAME", "Otniel")
    monkeypatch.setattr("api.ai.tools.read_inbox", _closed_mailbox)

    def invoke(_data, config=None):
        assert "configurable" not in config
        send_me_email.invoke(
            {
                "subject": "Nota",
                "content": "Olá,\n\nSegue.\n\nAté mais!\nOtniel\nAlex",
            },
            config=config,
        )
        return _messages(_reply("ok"))

    result = chat_turn(
        _context(pinned_recipient=None),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    draft = result.drafts[0]
    assert draft.recipient == "inbox@example.com"
    assert draft.kind == "created"
    assert "Alex" not in draft.body
    assert "Otniel" in draft.body
    assert os.environ["EMAIL_ADDRESS"] == "private-inbox@gmail.com"
    assert os.environ["EMAIL_SENDER_NAME"] == "Otniel"


def test_ambiguous_reply_asks_which_email_without_calling_the_supervisor(monkeypatch):
    def invoke(_data, _config=None):
        raise AssertionError("supervisor ran")

    held = _run("ambiguous-reply", invoke, monkeypatch)
    reply = held["trace"].assistant_reply.casefold()

    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()
    assert held["trace"].drafts == ()
    for term in (
        "João Mendes",
        "Fatura de março",
        "Fatura de abril",
        "1 de outubro de 2026",
        "2 de outubro de 2026",
    ):
        assert term in held["trace"].assistant_reply
    assert "pronto" not in reply
    assert "pronta" not in reply


def test_a_person_name_in_the_reply_still_names_the_recipient_address(monkeypatch):
    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Reunião",
                "content": "Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!",
            },
            config=config,
        )
        return _messages(_reply("O rascunho está pronto para João."))

    held = _run("pin-wins", invoke, monkeypatch)

    assert "ana@example.com" in held["trace"].assistant_reply
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_pinned_recipient_is_stated_for_a_new_email(monkeypatch):
    def invoke(data, config=None):
        text = data["messages"][0]["content"]
        assert "ana@example.com" in text
        assert "Pinned recipient" in text
        send_me_email.invoke(
            {
                "subject": "Latte",
                "content": (
                    "Olá,\n\n"
                    "Passos de um latte: aqueça o leite e extraia o espresso.\n\n"
                    "Até mais!"
                ),
            },
            config=config,
        )
        return _messages(
            _reply("", tool_calls=[{"name": "research_email", "args": {}, "id": "1"}]),
            _reply(_READY),
        )

    held = _run("research", invoke, monkeypatch)

    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_ambiguous_reply_reads_the_case_inbox_newest_first(monkeypatch):
    emails = (
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
    )
    seen = {}

    def invoke(data, _config=None):
        text = data["messages"][0]["content"]
        assert text.index("Fatura de abril") < text.index("Fatura de março")
        seen["recent"] = get_recent_emails.invoke({"limit": 10, "hours_ago": 1})
        seen["unread"] = get_unread_emails.invoke({"hours_ago": 1})
        return _messages(_reply("Segue a lista."))

    chat_turn(
        _context(
            case_id="list-inbox",
            chat_message="Lista a caixa.",
            pinned_recipient=None,
            inbound_emails=emails,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert seen["recent"].index("Fatura de abril") < seen["recent"].index("Fatura de março")
    assert seen["unread"].index("joao-abril") < seen["unread"].index("joao-marco")
    assert "marina@example.com" not in seen["recent"]


def test_unread_tool_keeps_case_order_and_skips_read_mail(monkeypatch):
    monkeypatch.setattr("api.ai.tools.read_inbox", _closed_mailbox)
    emails = (
        InboundEmail(
            id="new",
            sender="Ana",
            address="ana@example.com",
            subject="Nova",
            date="2 de outubro de 2026",
            body="nova",
            unread=True,
        ),
        InboundEmail(
            id="old",
            sender="Ana",
            address="ana@example.com",
            subject="Antiga",
            date="1 de outubro de 2026",
            body="antiga",
            unread=False,
        ),
    )
    seen = {}

    def invoke(_data, _config=None):
        seen["recent"] = get_recent_emails.invoke({"limit": 10, "unread_only": False})
        seen["unread"] = get_unread_emails.invoke({})
        seen["recent_unread"] = get_recent_emails.invoke({"unread_only": True})
        return _messages(_reply("ok"))

    chat_turn(
        _context(inbound_emails=emails, pinned_recipient=None),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert seen["recent"].index("Nova") < seen["recent"].index("Antiga")
    assert "Nova" in seen["unread"]
    assert "Antiga" not in seen["unread"]
    assert "Nova" in seen["recent_unread"]
    assert "Antiga" not in seen["recent_unread"]


def test_revision_updates_the_seeded_draft(monkeypatch):
    def invoke(data, _config=None):
        text = data["messages"][0]["content"]
        assert "00000000-0000-4000-8000-000000000003" in text
        assert "none" not in text
        revise_email_draft.invoke(
            {
                "draft_id": "00000000-0000-4000-8000-000000000003",
                "subject": "Reunião",
                "content": (
                    "Olá, Ana,\n\nA reunião está marcada para quinta.\n\nAté mais!"
                ),
            }
        )
        return _messages(_reply(_READY))

    held = _run("revision", invoke, monkeypatch)
    draft = held["trace"].drafts[0]

    assert held["score"].turn_accuracy == 1
    assert draft.id == "00000000-0000-4000-8000-000000000003"
    assert draft.kind == "revised"
    assert draft.recipient == "ana@example.com"


def test_identified_reply_ignores_the_pin(monkeypatch):
    def invoke(data, config=None):
        assert config["configurable"]["to_email"] == "ana@example.com"
        assert "Pinned recipient" not in data["messages"][0]["content"]
        send_me_email.invoke(
            {
                "subject": "Re: Contrato",
                "content": (
                    "Olá, Marina,\n\nO contrato segue para assinatura.\n\nAté mais!"
                ),
                "to_email": "marina@example.com",
                "reply": True,
                "inbound_id": "marina-contrato",
            },
            config=config,
        )
        return _messages(_reply(_MARINA_READY))

    held = _run("identified-reply", invoke, monkeypatch)

    assert held["score"].turn_accuracy == 1
    assert held["trace"].drafts[0].recipient == "marina@example.com"
    assert held["trace"].drafts[0].subject == "Re: Contrato"
    assert held["trace"].drafts[0].kind == "created"


def test_research_tool_model_call_counts_in_the_turn_cost(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "gpt-5-mini")

    class _LLM:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages, config=None):
            message = _reply(
                "",
                usage={"input_tokens": 1_000_000, "output_tokens": 0},
                model="gpt-5-mini",
            )
            response = SimpleNamespace(
                generations=[[SimpleNamespace(message=message)]]
            )
            for handler in (config or {}).get("callbacks") or []:
                handler.on_chat_model_end(response)
            return SimpleNamespace(
                subject="Latte",
                contents="leite",
                invalid_request=False,
            )

    import api.ai.services as services

    monkeypatch.setattr(services, "get_openai_llm", lambda: _LLM())

    def invoke(_data, config=None):
        research_email.invoke({"query": "passos de um latte"})
        send_me_email.invoke(
            {
                "subject": "Latte",
                "content": (
                    "Olá,\n\n"
                    "Passos de um latte: aqueça o leite e extraia o espresso.\n\n"
                    "Até mais!"
                ),
            },
            config=config,
        )
        return _messages(_reply(_READY))

    held = _run("research", invoke, monkeypatch)

    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()
    assert held["score"].cost == pytest.approx(0.25)


def test_research_without_a_draft_fails_draft_outcome(monkeypatch):
    def invoke(_data, _config=None):
        return _messages(
            _reply(
                "",
                tool_calls=[{"name": "research_email", "args": {}, "id": "1"}],
            ),
            _reply("Preciso de um destinatário."),
        )

    held = _run("research", invoke, monkeypatch)

    assert held["trace"].drafts == ()
    assert held["score"].turn_accuracy == 0
    assert held["score"].failed_checks[0] == "draft-outcome"


def test_an_english_ready_line_is_restated_for_a_portuguese_message(monkeypatch):
    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Latte",
                "content": (
                    "Olá,\n\n"
                    "Passos de um latte: aqueça o leite e extraia o espresso.\n\n"
                    "Até mais!"
                ),
            },
            config=config,
        )
        return _messages(
            _reply(
                "",
                tool_calls=[{"name": "research_email", "args": {}, "id": "1"}],
            ),
            _reply("A draft is ready and addressed to ana@example.com."),
        )

    held = _run("research", invoke, monkeypatch)

    assert "pronto" in held["trace"].assistant_reply.casefold()
    assert held["trace"].drafts[0].body.count("Até mais!") == 1
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_research_case_records_the_tool_and_the_draft(monkeypatch):
    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Latte",
                "content": (
                    "Olá,\n\n"
                    "Passos de um latte: aqueça o leite e extraia o espresso.\n\n"
                    "Até mais!"
                ),
            },
            config=config,
        )
        return _messages(
            _reply("", tool_calls=[{"name": "research_email", "args": {}, "id": "1"}]),
            _reply(_READY),
        )

    held = _run("research", invoke, monkeypatch)

    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()
    assert held["trace"].drafts[0].recipient == "ana@example.com"


def test_supervisor_is_built_under_the_synthetic_identity_and_restored(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "private-inbox@gmail.com")
    monkeypatch.setenv("EMAIL_SENDER_NAME", "Otniel")
    seen = {}

    def factory():
        seen["address"] = os.environ["EMAIL_ADDRESS"]
        seen["sender"] = os.environ["EMAIL_SENDER_NAME"]
        return _Supervisor(lambda _data, config=None: _messages(_reply("ok")))

    chat_turn(_context(), supervisor_factory=factory)

    assert seen == {
        "address": "inbox@example.com",
        "sender": "Alex",
    }
    assert os.environ["EMAIL_ADDRESS"] == "private-inbox@gmail.com"
    assert os.environ["EMAIL_SENDER_NAME"] == "Otniel"


def test_a_failed_supervisor_build_restores_the_identity(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "private-inbox@gmail.com")
    monkeypatch.setenv("EMAIL_SENDER_NAME", "Otniel")

    def factory():
        raise RuntimeError("supervisor failed")

    with pytest.raises(RuntimeError):
        chat_turn(_context(), supervisor_factory=factory)

    assert os.environ["EMAIL_ADDRESS"] == "private-inbox@gmail.com"
    assert os.environ["EMAIL_SENDER_NAME"] == "Otniel"


def test_latency_and_cost_belong_to_the_supervisor_call(monkeypatch):
    ticks = []

    def clock():
        ticks.append(1)
        return (10.0, 10.4)[len(ticks) - 1]

    monkeypatch.setattr("api.evaluation.time.perf_counter", clock)
    judged = []

    def invoke(_data, _config=None):
        return _messages(
            _reply(
                "",
                usage={"input_tokens": 1_000_000, "output_tokens": 0},
                model="gpt-5-mini-2025-08-07",
                tool_calls=[{"name": "research_email", "args": {}, "id": "1"}],
            ),
            _reply(
                _READY,
                usage={
                    "input_tokens": 0,
                    "output_tokens": 1_000_000,
                    "input_token_details": {"cache_read": 0},
                },
                model="gpt-5-mini",
            ),
        )

    def judge(_request):
        judged.append(1)
        return scripted_judge(_request)

    experiment = run_experiment(
        lambda context: chat_turn(
            context, supervisor_factory=lambda: _Supervisor(invoke)
        ),
        judge,
        case_ids=("pin-wins",),
    )

    assert judged == [1]
    assert len(ticks) == 2
    assert experiment.cases[0].latency == pytest.approx(0.4)
    assert experiment.cases[0].cost == 2.25


def test_cached_input_uses_the_lower_rate():
    def invoke(_data, _config=None):
        return _messages(
            _reply(
                _READY,
                usage={
                    "input_tokens": 1_000_000,
                    "output_tokens": 0,
                    "input_token_details": {"cache_read": 1_000_000},
                },
                model="gpt-5-mini",
            )
        )

    result = chat_turn(
        _context(),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.cost == pytest.approx(0.025)


def test_gpt_4o_mini_usage_uses_its_published_rates():
    def invoke(_data, _config=None):
        return _messages(
            _reply(
                _READY,
                usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
                model="gpt-4o-mini",
            )
        )

    result = chat_turn(
        _context(),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.cost == pytest.approx(0.75)


def test_a_supervisor_that_returns_nothing_scores_the_turn():
    def invoke(_data, _config=None):
        return {"messages": []}

    experiment = run_experiment(
        lambda context: chat_turn(
            context, supervisor_factory=lambda: _Supervisor(invoke)
        ),
        scripted_judge,
        case_ids=("pin-wins",),
    )

    assert experiment.cases[0].turn_accuracy == 0
    assert experiment.cases[0].failed_checks == ("turn",)
    assert experiment.cases[0].latency == 0
    assert experiment.cases[0].cost == 0


def test_unknown_model_usage_does_not_invent_a_cost():
    def invoke(_data, _config=None):
        return _messages(
            _reply(
                _READY,
                usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
                model="some-other-model",
            )
        )

    result = chat_turn(
        _context(),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.cost == 0
