"""The Experiment's chat turn uses the real Draft and inbox tools."""

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from api.ai.schemas import EmailMessageSchema
from api.drafts import DRAFT_OPEN, Draft, list_open_drafts
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
_LATTE_BODY = (
    "Olá,\n\n"
    "Passos de um latte: aqueça o leite e extraia o espresso.\n\n"
    "Até mais!"
)
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


def test_live_chat_and_experiment_share_one_scripted_send(monkeypatch):
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_ADDRESS", "inbox@example.com")
    monkeypatch.setenv("EMAIL_SENDER_NAME", "Alex")
    monkeypatch.setattr("api.ai.tools.read_inbox", _closed_mailbox)
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)

    from api.chat.models import (
        ChatMenssagePayload,
        ChatMessage,
        InboundEmailSnapshot,
    )
    from api.chat.routing import chat_create_message, chat_list_messages

    message = "Manda um email para o João dizendo que a reunião passou para sexta."
    inbound = InboundEmail(
        id="marina-contrato",
        sender="Marina Alves",
        address="marina@example.com",
        subject="Contrato",
        date="3 de outubro de 2026",
        body="O contrato precisa de assinatura até sexta.",
    )
    inbox_views: list[str] = []

    def invoke(data, config=None):
        assert config["configurable"]["to_email"] == "ana@example.com"
        inbox_views.append(get_recent_emails.invoke({"limit": 10}))
        send_me_email.invoke(
            {
                "subject": "Reunião",
                "content": (
                    "Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!\nAlex"
                ),
            },
            config=config,
        )
        return _messages(_reply("O modelo escreveu outra frase."))

    monkeypatch.setattr(
        "api.chat.routing.get_supervisor",
        lambda: _Supervisor(invoke),
    )
    route_engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        route_engine, tables=[Draft.__table__, ChatMessage.__table__]
    )
    route_session = Session(route_engine)
    route = chat_create_message(
        ChatMenssagePayload(
            message=message,
            to_email="ana@example.com",
            inbound_emails=[
                InboundEmailSnapshot(
                    id=inbound.id,
                    sender=inbound.sender,
                    address=inbound.address,
                    subject=inbound.subject,
                    date=inbound.date,
                    body=inbound.body,
                )
            ],
        ),
        route_session,
    )
    experiment = chat_turn(
        _context(
            chat_message=message,
            pinned_recipient="ana@example.com",
            default_inbox="inbox@example.com",
            sender_name="Alex",
            inbound_emails=(inbound,),
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    ready = "O rascunho está pronto para ana@example.com."
    body = "Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!"
    assert route["content"] == ready
    assert experiment.assistant_reply == ready
    assert len(route["drafts"]) == 1
    assert len(experiment.drafts) == 1
    route_draft = route["drafts"][0]
    experiment_draft = experiment.drafts[0]
    assert route_draft["subject"] == "Reunião"
    assert route_draft["body"] == body
    assert route_draft["recipient"] == "ana@example.com"
    assert experiment_draft.subject == route_draft["subject"]
    assert experiment_draft.body == route_draft["body"]
    assert experiment_draft.recipient == route_draft["recipient"]
    assert experiment_draft.kind == "created"
    assert len(inbox_views) == 2
    assert all("Contrato" in view and "Error" not in view for view in inbox_views)
    listed = chat_list_messages(route_session)
    assert [item.message for item in listed] == [message]


def test_live_chat_and_experiment_share_one_scripted_revision(monkeypatch):
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_ADDRESS", "inbox@example.com")
    monkeypatch.setenv("EMAIL_SENDER_NAME", "Alex")
    monkeypatch.setattr("api.ai.tools.read_inbox", _closed_mailbox)
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)

    from api.chat.models import ChatMenssagePayload, ChatMessage, OpenDraftSnapshot
    from api.chat.routing import chat_create_message
    from api.evaluation import OpenDraft

    message = "Manda esse email com o assunto Reunião."
    draft_id = "00000000-0000-4000-8000-000000000003"
    old_body = "Olá, Ana,\n\nA reunião está marcada para sexta.\n\nAté mais!"
    new_body = "Olá, Ana,\n\nA reunião está marcada para quinta.\n\nAté mais!"

    def invoke(data, _config=None):
        assert draft_id in data["messages"][0]["content"]
        revise_email_draft.invoke(
            {
                "draft_id": draft_id,
                "subject": "Reunião",
                "content": new_body,
            }
        )
        return _messages(_reply("O modelo escreveu outra frase."))

    def seed(session):
        session.add(
            Draft(
                id=uuid.UUID(draft_id),
                subject="Assunto antigo",
                body=old_body,
                recipient="ana@example.com",
                state=DRAFT_OPEN,
            )
        )
        session.commit()

    monkeypatch.setattr(
        "api.chat.routing.get_supervisor",
        lambda: _Supervisor(invoke),
    )
    route_engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        route_engine, tables=[Draft.__table__, ChatMessage.__table__]
    )
    route_session = Session(route_engine)
    seed(route_session)
    route = chat_create_message(
        ChatMenssagePayload(
            message=message,
            to_email="ana@example.com",
            open_drafts=[
                OpenDraftSnapshot(
                    id=draft_id,
                    subject="Assunto antigo",
                    body=old_body,
                    recipient="ana@example.com",
                )
            ],
        ),
        route_session,
    )
    experiment_session = _session()
    seed(experiment_session)
    experiment = chat_turn(
        _context(
            chat_message=message,
            pinned_recipient="ana@example.com",
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Assunto antigo",
                    body=old_body,
                ),
            ),
            session=experiment_session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    ready = "O rascunho está pronto para ana@example.com."
    assert route["content"] == ready
    assert experiment.assistant_reply == ready
    assert len(route["drafts"]) == 1
    assert route["drafts"][0]["id"] == draft_id
    assert route["drafts"][0]["subject"] == "Reunião"
    assert route["drafts"][0]["body"] == old_body
    assert route["drafts"][0]["recipient"] == "ana@example.com"
    assert experiment.drafts[0].id == draft_id
    assert experiment.drafts[0].kind == "revised"
    assert experiment.drafts[0].subject == route["drafts"][0]["subject"]
    assert experiment.drafts[0].body == route["drafts"][0]["body"]
    assert experiment.drafts[0].recipient == route["drafts"][0]["recipient"]
    stored = list_open_drafts(route_session)
    assert len(stored) == 1
    assert stored[0].subject == "Reunião"
    assert stored[0].body == old_body


def test_a_skipped_send_is_a_failed_creation_on_both_paths(monkeypatch):
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_ADDRESS", "inbox@example.com")
    monkeypatch.setenv("EMAIL_SENDER_NAME", "Alex")
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)

    from api.chat.models import ChatMenssagePayload, ChatMessage
    from api.chat.routing import chat_create_message, chat_list_messages

    message = (
        "Manda um email para ana@example.com dizendo que a reunião passou para sexta."
    )

    def invoke(_data, _config=None):
        return _messages(_reply("O rascunho está pronto para ana@example.com."))

    monkeypatch.setattr(
        "api.chat.routing.get_supervisor",
        lambda: _Supervisor(invoke),
    )
    route_engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        route_engine, tables=[Draft.__table__, ChatMessage.__table__]
    )
    route_session = Session(route_engine)
    route_session.add(
        Draft(
            id=uuid.UUID("00000000-0000-4000-8000-000000000041"),
            subject="Original",
            body="corpo",
            recipient="bia@example.com",
            state=DRAFT_OPEN,
        )
    )
    route_session.commit()
    route = chat_create_message(
        ChatMenssagePayload(message=message, to_email="ana@example.com"),
        route_session,
    )
    experiment = chat_turn(
        _context(
            chat_message=message,
            pinned_recipient="ana@example.com",
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert experiment.drafts == ()
    assert experiment.outcome == "creation failed"
    assert route["drafts"] == []
    assert route["outcome"] == "creation failed"
    assert [item.message for item in chat_list_messages(route_session)] == [message]
    stored = list_open_drafts(route_session)
    assert [(item.subject, item.body, item.recipient) for item in stored] == [
        ("Original", "corpo", "bia@example.com")
    ]


def test_a_stored_send_is_ready_in_the_language_of_the_chat_message(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    monkeypatch.setattr("api.ai.tools.read_inbox", _closed_mailbox)

    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Friday",
                "content": "Hello,\n\nThe meeting moved.\n\nTalk soon!",
            },
            config=config,
        )
        return _messages(_reply("Done."))

    portuguese = chat_turn(
        _context(
            chat_message=(
                "Manda um email para ana@example.com dizendo que a reunião passou para sexta."
            ),
            pinned_recipient="ana@example.com",
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )
    english = chat_turn(
        _context(
            chat_message="Send a note saying the meeting moved.",
            pinned_recipient="ana@example.com",
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert portuguese.outcome is None
    assert portuguese.assistant_reply == "O rascunho está pronto para ana@example.com."
    assert portuguese.drafts[0].recipient == "ana@example.com"
    assert english.outcome is None
    assert english.assistant_reply == "The draft is ready for ana@example.com."
    assert english.drafts[0].recipient == "ana@example.com"


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


def test_a_sent_claim_is_replaced_by_the_ready_sentence(monkeypatch):
    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Reunião",
                "content": "Olá, João,\n\nA reunião passou para sexta.\n\nAté mais!",
            },
            config=config,
        )
        return _messages(
            _reply(
                "Draft created for ana@example.com. "
                "It will be sent only after you confirm. "
                "O email foi enviado."
            )
        )

    held = _run("pin-wins", invoke, monkeypatch)

    assert held["trace"].assistant_reply == _READY
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


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


def test_an_ambiguous_reply_still_stores_the_clear_new_draft(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    inbounds = (
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

    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Sexta",
                "content": "Olá,\n\nA reunião passou para sexta.\n\nAté mais!",
                "to_email": "ana@example.com",
            },
            config=config,
        )
        return _messages(_reply("O rascunho está pronto para ana@example.com."))

    result = chat_turn(
        _context(
            chat_message="Responde o email do João e manda outro para ana@example.com.",
            pinned_recipient=None,
            inbound_emails=inbounds,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.outcome == "question"
    assert len(result.drafts) == 1
    assert result.drafts[0].recipient == "ana@example.com"
    assert result.drafts[0].kind == "created"
    assert result.assistant_reply.startswith("Qual email?")
    assert "João Mendes, Fatura de abril, 2 de outubro de 2026" in result.assistant_reply
    assert "João Mendes, Fatura de março, 1 de outubro de 2026" in result.assistant_reply
    assert "pronto" not in result.assistant_reply.casefold()
    assert result.revision is None


def _two_joao_emails():
    return (
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


def test_an_ambiguous_reply_beside_a_missed_revision_keeps_the_cards(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    body = "Olá,\n\nTexto.\n\nAté mais!"
    first_id = "00000000-0000-4000-8000-000000000061"
    second_id = "00000000-0000-4000-8000-000000000062"
    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(first_id),
            subject="Original",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.add(
        Draft(
            id=uuid.UUID(second_id),
            subject="Outro",
            body=body,
            recipient="bia@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Sexta",
                "content": "Olá,\n\nA reunião passou para sexta.\n\nAté mais!",
                "to_email": "ana@example.com",
            },
            config=config,
        )
        return _messages(_reply("O rascunho está pronto para ana@example.com."))

    result = chat_turn(
        _context(
            chat_message=(
                "Responde o email do João e manda outro para ana@example.com, "
                "e muda o assunto para Reunião."
            ),
            pinned_recipient=None,
            inbound_emails=_two_joao_emails(),
            open_drafts=(
                OpenDraft(
                    id=first_id,
                    recipient="ana@example.com",
                    subject="Original",
                    body=body,
                ),
                OpenDraft(
                    id=second_id,
                    recipient="bia@example.com",
                    subject="Outro",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.outcome == "question"
    assert result.revision == "failed"
    assert result.assistant_reply.startswith("Qual email?")
    assert "pronto" not in result.assistant_reply.casefold()
    assert [draft.subject for draft in result.drafts] == ["Sexta"]
    assert result.drafts[0].recipient == "ana@example.com"
    assert [item.subject for item in list_open_drafts(session)] == [
        "Original",
        "Outro",
        "Sexta",
    ]


def test_an_ambiguous_reply_still_updates_the_one_open_draft(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    called = []
    draft_id = "00000000-0000-4000-8000-000000000063"
    body = "Olá,\n\nTexto.\n\nAté mais!"
    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(draft_id),
            subject="Original",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("Qual email?"))

    result = chat_turn(
        _context(
            chat_message=(
                "Responde o email do João e muda o assunto para Reunião."
            ),
            pinned_recipient=None,
            inbound_emails=_two_joao_emails(),
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Original",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert called == []
    assert result.outcome == "question"
    assert result.revision is None
    assert result.assistant_reply.startswith("Qual email?")
    assert result.drafts[0].id == draft_id
    assert result.drafts[0].subject == "Reunião"
    assert result.drafts[0].body == body
    assert list_open_drafts(session)[0].subject == "Reunião"


def test_a_closing_change_is_not_a_failed_creation(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    draft_id = "00000000-0000-4000-8000-000000000064"
    body = "Olá,\n\nTexto.\n\nAté mais!"
    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(draft_id),
            subject="Original",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    def invoke(_data, _config=None):
        return _messages(_reply("O rascunho está pronto para ana@example.com."))

    result = chat_turn(
        _context(
            chat_message="Envia esse email com outro fechamento.",
            pinned_recipient=None,
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Original",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.outcome is None
    assert result.drafts == ()
    assert result.assistant_reply == "O rascunho está pronto para ana@example.com."
    assert list_open_drafts(session)[0].subject == "Original"
    assert list_open_drafts(session)[0].body == body


def test_a_question_beside_a_missed_revision_keeps_the_card(monkeypatch):
    called = []
    body = "Olá,\n\nTexto.\n\nAté mais!"

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("O rascunho está pronto."))

    session = _session()
    first_id = "00000000-0000-4000-8000-000000000051"
    second_id = "00000000-0000-4000-8000-000000000052"
    session.add(
        Draft(
            id=uuid.UUID(first_id),
            subject="Original",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.add(
        Draft(
            id=uuid.UUID(second_id),
            subject="Outro",
            body=body,
            recipient="bia@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    result = chat_turn(
        _context(
            chat_message=(
                "Pesquisa o café e manda para ana@example.com e para "
                "bruno@example.com, e muda o assunto para Reunião."
            ),
            pinned_recipient=None,
            open_drafts=(
                OpenDraft(
                    id=first_id,
                    recipient="ana@example.com",
                    subject="Original",
                    body=body,
                ),
                OpenDraft(
                    id=second_id,
                    recipient="bia@example.com",
                    subject="Outro",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert called == []
    assert result.outcome == "question"
    assert result.revision == "failed"
    assert result.drafts == ()
    assert result.assistant_reply == (
        "Qual endereço? ana@example.com ou bruno@example.com."
    )
    assert [item.subject for item in list_open_drafts(session)] == ["Original", "Outro"]


def test_two_addresses_ask_and_still_update_the_open_draft(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    called = []
    draft_id = "00000000-0000-4000-8000-000000000041"
    body = "Olá,\n\nTexto.\n\nAté mais!"

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(
            _reply(
                "Subject: Café:\nBody: O preço subiu.",
                name="research_email",
            ),
            _reply("O rascunho está pronto para ana@example.com."),
        )

    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(draft_id),
            subject="Assunto antigo",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    result = chat_turn(
        _context(
            chat_message=(
                "Pesquisa o café e manda para ana@example.com e para "
                "bruno@example.com, e muda o assunto para Reunião."
            ),
            pinned_recipient=None,
            default_inbox="inbox@example.com",
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Assunto antigo",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert called == []
    assert result.outcome == "question"
    assert result.drafts[0].id == draft_id
    assert result.drafts[0].subject == "Reunião"
    assert result.drafts[0].kind == "revised"
    assert len(result.drafts) == 1
    assert result.assistant_reply == (
        "Qual endereço? ana@example.com ou bruno@example.com."
    )
    assert "pronto" not in result.assistant_reply.casefold()
    assert list_open_drafts(session)[0].subject == "Reunião"


def test_a_revision_and_a_new_draft_share_one_ready_sentence(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    draft_id = "00000000-0000-4000-8000-000000000003"
    body = "Olá, Ana,\n\nA reunião está marcada para sexta.\n\nAté mais!"
    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(draft_id),
            subject="Assunto antigo",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Sexta",
                "content": "Olá,\n\nA reunião passou para sexta.\n\nAté mais!",
                "to_email": "bia@example.com",
            },
            config=config,
        )
        return _messages(_reply("Pronto."))

    result = chat_turn(
        _context(
            chat_message=(
                "Manda um email para bia@example.com dizendo que a reunião "
                "passou para sexta, e muda o assunto para Reunião."
            ),
            pinned_recipient=None,
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Assunto antigo",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    by_subject = {draft.subject: draft for draft in result.drafts}
    assert by_subject["Reunião"].id == draft_id
    assert by_subject["Reunião"].kind == "revised"
    assert by_subject["Reunião"].body == body
    assert by_subject["Sexta"].recipient == "bia@example.com"
    assert by_subject["Sexta"].kind == "created"
    assert result.outcome == "ready"
    assert result.assistant_reply == (
        "O rascunho está pronto para bia@example.com, e o outro foi atualizado."
    )


def test_an_english_combined_message_names_the_new_recipient(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    draft_id = "00000000-0000-4000-8000-000000000004"
    body = "Hello,\n\nThe meeting is on Friday.\n\nTalk soon!"
    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(draft_id),
            subject="Old subject",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Friday",
                "content": "Hello,\n\nThe meeting moved.\n\nTalk soon!",
                "to_email": "bia@example.com",
            },
            config=config,
        )
        return _messages(_reply("Done."))

    result = chat_turn(
        _context(
            chat_message=(
                "Send an email to bia@example.com and change the subject to Meeting."
            ),
            pinned_recipient=None,
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Old subject",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.outcome == "ready"
    assert result.assistant_reply == (
        "The draft is ready for bia@example.com, and the other was updated."
    )
    by_subject = {draft.subject: draft for draft in result.drafts}
    assert by_subject["Meeting"].id == draft_id
    assert by_subject["Friday"].recipient == "bia@example.com"


def test_each_part_of_a_combined_message_can_fail_on_its_own(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    message = (
        "Manda um email para bia@example.com dizendo que a reunião "
        "passou para sexta, e muda o assunto para Reunião."
    )
    body = "Olá, Ana,\n\nA reunião está marcada para sexta.\n\nAté mais!"
    from api.evaluation import OpenDraft

    def seed(session, drafts):
        for draft in drafts:
            session.add(draft)
        session.commit()

    only_id = "00000000-0000-4000-8000-000000000021"
    only_session = _session()
    seed(
        only_session,
        [
            Draft(
                id=uuid.UUID(only_id),
                subject="Assunto antigo",
                body=body,
                recipient="ana@example.com",
                state=DRAFT_OPEN,
            )
        ],
    )

    def no_send(_data, _config=None):
        return _messages(_reply("O rascunho está pronto para bia@example.com."))

    revised_only = chat_turn(
        _context(
            chat_message=message,
            pinned_recipient=None,
            open_drafts=(
                OpenDraft(
                    id=only_id,
                    recipient="ana@example.com",
                    subject="Assunto antigo",
                    body=body,
                ),
            ),
            session=only_session,
        ),
        supervisor_factory=lambda: _Supervisor(no_send),
    )
    assert revised_only.outcome == "creation failed"
    assert revised_only.assistant_reply == ""
    assert revised_only.drafts[0].subject == "Reunião"
    assert revised_only.drafts[0].id == only_id
    assert list_open_drafts(only_session)[0].subject == "Reunião"

    def send_only(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Sexta",
                "content": "Olá,\n\nA reunião passou para sexta.\n\nAté mais!",
                "to_email": "bia@example.com",
            },
            config=config,
        )
        return _messages(_reply("Pronto."))

    pair_session = _session()
    first_id = "00000000-0000-4000-8000-000000000031"
    second_id = "00000000-0000-4000-8000-000000000032"
    seed(
        pair_session,
        [
            Draft(
                id=uuid.UUID(first_id),
                subject="Original",
                body=body,
                recipient="ana@example.com",
                state=DRAFT_OPEN,
            ),
            Draft(
                id=uuid.UUID(second_id),
                subject="Outro",
                body=body,
                recipient="bia@example.com",
                state=DRAFT_OPEN,
            ),
        ],
    )
    open_pair = (
        OpenDraft(id=first_id, recipient="ana@example.com", subject="Original", body=body),
        OpenDraft(id=second_id, recipient="bia@example.com", subject="Outro", body=body),
    )
    new_only = chat_turn(
        _context(
            chat_message=message,
            pinned_recipient=None,
            open_drafts=open_pair,
            session=pair_session,
        ),
        supervisor_factory=lambda: _Supervisor(send_only),
    )
    assert new_only.outcome == "revision failed"
    assert new_only.assistant_reply == ""
    assert len(new_only.drafts) == 1
    assert new_only.drafts[0].subject == "Sexta"
    assert new_only.drafts[0].recipient == "bia@example.com"
    assert [item.subject for item in list_open_drafts(pair_session)] == [
        "Original",
        "Outro",
        "Sexta",
    ]

    stayed = _session()
    seed(
        stayed,
        [
            Draft(
                id=uuid.UUID(first_id),
                subject="Original",
                body=body,
                recipient="ana@example.com",
                state=DRAFT_OPEN,
            ),
            Draft(
                id=uuid.UUID(second_id),
                subject="Outro",
                body=body,
                recipient="bia@example.com",
                state=DRAFT_OPEN,
            ),
        ],
    )
    neither = chat_turn(
        _context(
            chat_message=message,
            pinned_recipient=None,
            open_drafts=open_pair,
            session=stayed,
        ),
        supervisor_factory=lambda: _Supervisor(no_send),
    )
    assert neither.outcome == "both failed"
    assert neither.assistant_reply == ""
    assert neither.drafts == ()
    assert [item.subject for item in list_open_drafts(stayed)] == ["Original", "Outro"]


def test_a_revision_that_says_manda_updates_the_only_open_draft(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)
    called = []
    draft_id = "00000000-0000-4000-8000-000000000003"
    body = "Olá, Ana,\n\nA reunião está marcada para sexta.\n\nAté mais!"

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("O rascunho está pronto para outra pessoa."))

    session = _session()
    session.add(
        Draft(
            id=uuid.UUID(draft_id),
            subject="Assunto antigo",
            body=body,
            recipient="ana@example.com",
            state=DRAFT_OPEN,
        )
    )
    session.commit()
    from api.evaluation import OpenDraft

    result = chat_turn(
        _context(
            chat_message="Manda esse email com o assunto Reunião.",
            pinned_recipient="ana@example.com",
            open_drafts=(
                OpenDraft(
                    id=draft_id,
                    recipient="ana@example.com",
                    subject="Assunto antigo",
                    body=body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert called == []
    assert result.outcome is None
    assert result.assistant_reply == "O rascunho está pronto para ana@example.com."
    assert len(result.drafts) == 1
    assert result.drafts[0].id == draft_id
    assert result.drafts[0].kind == "revised"
    assert result.drafts[0].subject == "Reunião"
    assert result.drafts[0].body == body
    assert result.drafts[0].recipient == "ana@example.com"
    stored = list_open_drafts(session)
    assert stored[0].subject == "Reunião"


def test_a_revision_with_no_open_draft_is_not_a_failed_creation(monkeypatch):
    called = []

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("O rascunho está pronto."))

    portuguese = chat_turn(
        _context(
            chat_message="Manda esse email com o assunto Reunião.",
            pinned_recipient=None,
            open_drafts=(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )
    english = chat_turn(
        _context(
            chat_message="Send this email with the subject Friday.",
            pinned_recipient=None,
            open_drafts=(),
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert called == []
    assert portuguese.drafts == ()
    assert portuguese.outcome == "question"
    assert portuguese.assistant_reply == "Não há rascunho para atualizar."
    assert english.drafts == ()
    assert english.outcome == "question"
    assert english.assistant_reply == "There is nothing to revise."


def test_two_open_drafts_ask_which_and_change_neither(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    called = []

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("O rascunho está pronto."))

    first = Draft(
        id=uuid.UUID("00000000-0000-4000-8000-000000000011"),
        subject="Original",
        body="Olá,\n\nPrimeiro.\n\nAté mais!",
        recipient="ana@example.com",
        state=DRAFT_OPEN,
    )
    second = Draft(
        id=uuid.UUID("00000000-0000-4000-8000-000000000012"),
        subject="Outro",
        body="Olá,\n\nSegundo.\n\nAté mais!",
        recipient="bia@example.com",
        state=DRAFT_OPEN,
    )
    session = _session()
    session.add(first)
    session.add(second)
    session.commit()
    from api.evaluation import OpenDraft

    result = chat_turn(
        _context(
            chat_message="Envia esse email com outro fechamento.",
            pinned_recipient=None,
            open_drafts=(
                OpenDraft(
                    id=str(first.id),
                    recipient=first.recipient,
                    subject=first.subject,
                    body=first.body,
                ),
                OpenDraft(
                    id=str(second.id),
                    recipient=second.recipient,
                    subject=second.subject,
                    body=second.body,
                ),
            ),
            session=session,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert called == []
    assert result.drafts == ()
    assert result.outcome == "question"
    assert result.assistant_reply == (
        "Qual rascunho? Original para ana@example.com, ou Outro para bia@example.com."
    )
    stored = list_open_drafts(session)
    assert [(item.subject, item.body) for item in stored] == [
        ("Original", "Olá,\n\nPrimeiro.\n\nAté mais!"),
        ("Outro", "Olá,\n\nSegundo.\n\nAté mais!"),
    ]


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


_INBOUND_CONTRACT = "O contrato precisa de assinatura até sexta."


def test_a_reply_drops_a_pasted_inbound_body(monkeypatch):
    def invoke(_data, config=None):
        send_me_email.invoke(
            {
                "subject": "Re: Contrato",
                "content": (
                    "Olá, Marina,\n\n"
                    f"{_INBOUND_CONTRACT}\n\n"
                    "O contrato segue para assinatura.\n\n"
                    "Até mais!"
                ),
                "to_email": "marina@example.com",
                "reply": True,
                "inbound_id": "marina-contrato",
            },
            config=config,
        )
        return _messages(_reply(_MARINA_READY))

    held = _run("identified-reply", invoke, monkeypatch)

    assert _INBOUND_CONTRACT not in held["trace"].drafts[0].body
    assert "assinatura" in held["trace"].drafts[0].body
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_a_reply_that_only_copies_the_inbound_email_is_not_stored(monkeypatch):
    seen = {}

    def invoke(_data, config=None):
        seen["tool"] = send_me_email.invoke(
            {
                "subject": "Re: Contrato",
                "content": (
                    "Olá, Marina,\n\n"
                    f"{_INBOUND_CONTRACT}\n\n"
                    "Até mais!"
                ),
                "to_email": "marina@example.com",
                "reply": True,
                "inbound_id": "marina-contrato",
            },
            config=config,
        )
        return _messages(_reply("Não consegui responder."))

    held = _run("identified-reply", invoke, monkeypatch)

    assert "copies the Inbound email" in seen["tool"]
    assert held["trace"].drafts == ()


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
                contents=_LATTE_BODY,
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


_LATTE_WITHOUT_STEPS = (
    "Olá,\n\n"
    "Aqueça o leite e extraia o espresso.\n\n"
    "Até mais!"
)


def _queued_composer(monkeypatch, contents: list[str]):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    queued = list(contents)
    calls: list[object] = []

    class _LLM:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages, config=None):
            calls.append(messages)
            message = _reply(
                "",
                usage={"input_tokens": 10, "output_tokens": 0},
                model="gpt-5-mini",
            )
            response = SimpleNamespace(
                generations=[[SimpleNamespace(message=message)]]
            )
            for handler in (config or {}).get("callbacks") or []:
                handler.on_chat_model_end(response)
            return SimpleNamespace(
                subject="Latte",
                contents=queued.pop(0),
                invalid_request=False,
            )

    import api.ai.services as services

    monkeypatch.setattr(services, "get_openai_llm", lambda: _LLM())
    return calls


def test_latte_research_retries_until_each_fact_wording_is_present(monkeypatch):
    calls = _queued_composer(
        monkeypatch,
        [_LATTE_WITHOUT_STEPS, _LATTE_BODY],
    )

    def invoke(_data, _config=None):
        research_email.invoke({"query": "passos de um latte"})
        return _messages(_reply("Segue o que encontrei."))

    held = _run("research", invoke, monkeypatch)

    assert len(calls) == 2
    assert "passos or etapas" in calls[0][0][1]
    assert held["trace"].drafts[0].body == _LATTE_BODY
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_latte_research_keeps_the_last_body_without_inserting_a_fact(monkeypatch):
    calls = _queued_composer(monkeypatch, [_LATTE_WITHOUT_STEPS] * 3)

    def invoke(_data, _config=None):
        research_email.invoke({"query": "passos de um latte"})
        return _messages(_reply("Segue o que encontrei."))

    held = _run("research", invoke, monkeypatch)

    assert len(calls) == 3
    assert held["trace"].drafts[0].body == _LATTE_WITHOUT_STEPS
    assert "passos" not in held["trace"].drafts[0].body
    assert "etapas" not in held["trace"].drafts[0].body
    assert held["score"].failed_checks == ("body-facts",)


def test_research_that_is_not_a_latte_calls_the_model_once(monkeypatch):
    calls = _queued_composer(monkeypatch, [_LATTE_WITHOUT_STEPS])

    def invoke(_data, _config=None):
        research_email.invoke({"query": "como trocar um pneu"})
        return _messages(_reply("Segue o que encontrei."))

    held = _run("research", invoke, monkeypatch)

    assert len(calls) == 1
    assert "passos or etapas" not in calls[0][0][1]
    assert held["trace"].drafts[0].body == _LATTE_WITHOUT_STEPS


def _latte_research(monkeypatch, contents: str = _LATTE_BODY, subject: str = "Latte"):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "api.ai.services.generate_email_message",
        lambda _query: EmailMessageSchema(
            subject=subject,
            contents=contents,
            invalid_request=False,
        ),
    )


def test_two_addresses_without_a_pin_ask_which_and_store_no_draft(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    called = []

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("O rascunho está pronto para ana@example.com."))

    portuguese = chat_turn(
        _context(
            chat_message=(
                "Pesquisa o preço do café e manda para ana@example.com e para bruno@example.com."
            ),
            pinned_recipient=None,
            default_inbox="inbox@example.com",
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )
    english = chat_turn(
        _context(
            chat_message=(
                "Research the coffee price and send it to ana@example.com and to bruno@example.com."
            ),
            pinned_recipient=None,
            default_inbox="inbox@example.com",
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert portuguese.drafts == ()
    assert portuguese.outcome is None
    assert portuguese.assistant_reply == (
        "Qual endereço? ana@example.com ou bruno@example.com."
    )
    assert "pronto" not in portuguese.assistant_reply.casefold()
    assert english.drafts == ()
    assert english.assistant_reply == (
        "Which address? ana@example.com or bruno@example.com."
    )
    assert "ready" not in english.assistant_reply.casefold()
    assert called == []


def test_an_invalid_address_without_a_pin_asks_for_a_valid_recipient(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    called = []

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(
            _reply(
                "Subject: Café:\nBody: O preço subiu.",
                name="research_email",
            ),
            _reply("O rascunho está pronto para inbox@example.com."),
        )

    portuguese = chat_turn(
        _context(
            chat_message="Pesquisa o preço do café e manda para ana@.",
            pinned_recipient=None,
            default_inbox="inbox@example.com",
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )
    english = chat_turn(
        _context(
            chat_message="Research the coffee price and send it to ana@.",
            pinned_recipient=None,
            default_inbox="inbox@example.com",
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert portuguese.drafts == ()
    assert portuguese.outcome is None
    assert portuguese.assistant_reply == "Informe um destinatário válido."
    assert "inbox@example.com" not in portuguese.assistant_reply
    assert english.drafts == ()
    assert english.assistant_reply == "Give a valid recipient."
    assert called == []


def test_no_recipient_anywhere_asks_and_stores_no_draft(monkeypatch):
    called = []

    def invoke(_data, _config=None):
        called.append(True)
        return _messages(_reply("O rascunho está pronto."))

    portuguese = chat_turn(
        _context(
            chat_message="Manda um email dizendo que a reunião passou para sexta.",
            pinned_recipient=None,
            default_inbox=None,
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )
    english = chat_turn(
        _context(
            chat_message="Send a note saying the meeting moved.",
            pinned_recipient=None,
            default_inbox=None,
            session=_session(),
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert portuguese.drafts == ()
    assert portuguese.outcome is None
    assert portuguese.assistant_reply == "Qual é o destinatário?"
    assert english.drafts == ()
    assert english.outcome is None
    assert english.assistant_reply == "Who is the recipient?"
    assert called == []


def test_a_pin_still_receives_the_draft_when_the_address_is_ambiguous(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)

    def invoke(_data, _config=None):
        return _messages(
            _reply(
                "Subject: Café:\nBody: O preço subiu.",
                name="research_email",
            ),
            _reply("Encontrei o preço."),
        )

    def run(message):
        return chat_turn(
            _context(
                chat_message=message,
                pinned_recipient="bia@example.com",
                default_inbox="inbox@example.com",
                session=_session(),
            ),
            supervisor_factory=lambda: _Supervisor(invoke),
        )

    two = run(
        "Pesquisa o preço do café e manda para ana@example.com e para bruno@example.com."
    )
    invalid = run("Pesquisa o preço do café e manda para ana@.")

    assert two.drafts[0].recipient == "bia@example.com"
    assert two.assistant_reply == "O rascunho está pronto para bia@example.com."
    assert two.outcome is None
    assert invalid.drafts[0].recipient == "bia@example.com"
    assert invalid.assistant_reply == "O rascunho está pronto para bia@example.com."


def test_research_without_the_send_tool_stores_one_outbound_draft(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)
    monkeypatch.setattr("api.myemailer.sender.send_mail", _closed_confirm)

    def invoke(_data, _config=None):
        return _messages(
            _reply(
                "Subject: Latte:\nBody: Aqueça o leite e extraia o espresso.",
                name="research_email",
            ),
            _reply("Segue o que encontrei, posso ajudar com mais."),
        )

    result = chat_turn(
        _context(
            chat_message=(
                "Pesquisa os passos de um latte e me manda por email para ana@example.com."
            ),
            pinned_recipient=None,
            default_inbox="inbox@example.com",
            sender_name="Alex",
        ),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert len(result.drafts) == 1
    draft = result.drafts[0]
    assert draft.recipient == "ana@example.com"
    assert draft.subject == "Latte"
    assert draft.body == (
        "Olá,\n\nAqueça o leite e extraia o espresso.\n\nAté mais!"
    )
    assert "posso ajudar" not in draft.body
    assert result.assistant_reply == "O rascunho está pronto para ana@example.com."
    assert result.outcome is None


@pytest.mark.parametrize(
    ("message", "reply"),
    [
        ("Lista meus emails.", "Você tem dois emails."),
        ("Pesquisa meus emails.", "Achei três conversas."),
        ("Email the notes to ana@example.com.", "Here are the notes."),
        ("Descobre os passos de um latte e me escreve.", "Segue o que escrevi."),
        ("ana@example.com", "Pode repetir o pedido?"),
    ],
)
def test_wording_that_does_not_ask_for_an_outbound_email_stores_no_draft(
    message, reply, monkeypatch
):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)

    def invoke(_data, _config=None):
        return _messages(
            _reply(
                "Subject: Latte:\nBody: Aqueça o leite e extraia o espresso.",
                name="research_email",
            ),
            _reply(reply),
        )

    result = chat_turn(
        _context(chat_message=message, pinned_recipient=None, session=_session()),
        supervisor_factory=lambda: _Supervisor(invoke),
    )

    assert result.drafts == ()
    assert result.outcome is None
    assert result.assistant_reply == reply


def test_research_recipient_follows_pinned_then_named_then_default_inbox(monkeypatch):
    monkeypatch.setattr("api.drafts.confirm_draft", _closed_confirm)

    def invoke(_data, _config=None):
        return _messages(
            _reply(
                "Subject: Café:\nBody: O preço subiu.",
                name="research_email",
            ),
            _reply("Encontrei o preço."),
        )

    def run(message, pinned):
        return chat_turn(
            _context(
                chat_message=message,
                pinned_recipient=pinned,
                default_inbox="inbox@example.com",
                session=_session(),
            ),
            supervisor_factory=lambda: _Supervisor(invoke),
        )

    pinned = run(
        "Pesquisa o preço do café e manda para ana@example.com.",
        "bruno@example.com",
    )
    named = run(
        "Pesquisa o preço do café e manda para ana@example.com.",
        None,
    )
    default = run("Pesquisa o preço do café e manda para a Ana.", None)

    assert pinned.drafts[0].recipient == "bruno@example.com"
    assert pinned.assistant_reply == "O rascunho está pronto para bruno@example.com."
    assert named.drafts[0].recipient == "ana@example.com"
    assert default.drafts[0].recipient == "inbox@example.com"
    assert default.assistant_reply == "O rascunho está pronto para inbox@example.com."
    assert all(
        draft.body == "Olá,\n\nO preço subiu.\n\nAté mais!"
        for draft in (pinned.drafts[0], named.drafts[0], default.drafts[0])
    )


def test_a_research_email_without_send_still_opens_one_draft(monkeypatch):
    _latte_research(monkeypatch)

    def invoke(_data, _config=None):
        research_email.invoke({"query": "passos de um latte"})
        return _messages(_reply("Segue o que encontrei."))

    held = _run("research", invoke, monkeypatch)
    draft = held["trace"].drafts[0]

    assert draft.recipient == "ana@example.com"
    assert draft.subject == "Latte"
    assert draft.body == _LATTE_BODY
    assert draft.kind == "created"
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_a_research_tool_message_opens_a_draft_when_send_does_not(monkeypatch):
    def invoke(_data, _config=None):
        return _messages(
            _reply(
                f"Subject: Latte:\nBody: {_LATTE_BODY}",
                name="research_email",
            ),
            _reply("Segue o que encontrei."),
        )

    held = _run("research", invoke, monkeypatch)
    draft = held["trace"].drafts[0]

    assert draft.subject == "Latte"
    assert draft.body == _LATTE_BODY
    assert draft.kind == "created"
    assert held["score"].turn_accuracy == 1
    assert held["score"].failed_checks == ()


def test_a_plain_email_does_not_store_a_research_result(monkeypatch):
    _latte_research(monkeypatch)

    def invoke(_data, _config=None):
        research_email.invoke({"query": "passos de um latte"})
        return _messages(_reply("Preciso de um destinatário."))

    held = _run("pin-wins", invoke, monkeypatch)

    assert held["trace"].drafts == ()


def test_an_email_agent_draft_is_kept_when_research_also_returns(monkeypatch):
    _latte_research(monkeypatch, contents="Olá,\n\noutro corpo\n\nAté mais!", subject="Outro")

    def invoke(_data, config=None):
        research_email.invoke({"query": "passos de um latte"})
        send_me_email.invoke(
            {"subject": "Latte", "content": _LATTE_BODY},
            config=config,
        )
        return _messages(_reply(_READY))

    held = _run("research", invoke, monkeypatch)

    assert len(held["trace"].drafts) == 1
    assert held["trace"].drafts[0].subject == "Latte"
    assert held["trace"].drafts[0].body == _LATTE_BODY
    assert held["score"].turn_accuracy == 1


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

    monkeypatch.setattr("api.chat.turn.time.perf_counter", clock)
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
