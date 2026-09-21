import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from api.drafts import (
    Draft,
    DraftNotFoundError,
    DraftNotOpenError,
    chat_turn_payload,
    collecting_created_drafts,
    confirm_draft,
    create_open_draft,
    discard_draft,
    list_open_drafts,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


def test_create_persists_open_draft_with_prepared_body_and_resolved_recipient(session):
    draft = create_open_draft(
        session,
        subject="AI research",
        body="Here is the research.\n[Seu nome]",
        pinned=None,
        named="named@example.com",
        default="default@example.com",
    )

    assert draft.state == "open"
    assert draft.subject == "AI research"
    assert draft.body == "Here is the research."
    assert draft.recipient == "named@example.com"
    assert isinstance(draft.id, uuid.UUID)


def test_create_lets_pinned_recipient_win(session):
    draft = create_open_draft(
        session,
        subject="Hello",
        body="Body",
        pinned="pinned@example.com",
        named="named@example.com",
        default="default@example.com",
    )

    assert draft.recipient == "pinned@example.com"


def test_create_rejects_invalid_named_recipient_without_persisting(session):
    with pytest.raises(ValueError, match="Invalid recipient email"):
        create_open_draft(
            session,
            subject="Hello",
            body="Body",
            pinned=None,
            named="not-an-email",
            default="default@example.com",
        )

    assert session.exec(select(Draft)).all() == []


def _open_draft(session, *, body: str = "Here is the research.") -> Draft:
    return create_open_draft(
        session,
        subject="AI research",
        body=body,
        pinned=None,
        named="named@example.com",
        default="default@example.com",
    )


def test_confirm_sends_current_card_fields_via_smtp_and_marks_sent(session):
    draft = _open_draft(session)
    sent: list[dict] = []

    def fake_send_mail(*, subject, content, to_email):
        sent.append({"subject": subject, "content": content, "to_email": to_email})

    result = confirm_draft(
        session,
        draft.id,
        subject="Edited subject",
        body="Edited body",
        recipient="edited@example.com",
        send_mail=fake_send_mail,
    )

    assert result.state == "sent"
    assert result.subject == "Edited subject"
    assert result.body == "Edited body"
    assert result.recipient == "edited@example.com"
    assert sent == [
        {
            "subject": "Edited subject",
            "content": "Edited body",
            "to_email": "edited@example.com",
        }
    ]
    assert session.get(Draft, draft.id).state == "sent"


def test_confirm_strips_placeholder_from_edited_body_before_smtp(session):
    draft = _open_draft(session)
    sent: list[dict] = []

    def fake_send_mail(*, subject, content, to_email):
        sent.append({"subject": subject, "content": content, "to_email": to_email})

    result = confirm_draft(
        session,
        draft.id,
        subject="AI research",
        body="Here is the research.\n[Seu nome]",
        recipient="named@example.com",
        send_mail=fake_send_mail,
    )

    assert result.body == "Here is the research."
    assert sent == [
        {
            "subject": "AI research",
            "content": "Here is the research.",
            "to_email": "named@example.com",
        }
    ]


def test_confirm_rejects_invalid_recipient_and_does_not_send(session):
    draft = _open_draft(session)
    sent: list[dict] = []

    def fake_send_mail(*, subject, content, to_email):
        sent.append({"subject": subject, "content": content, "to_email": to_email})

    with pytest.raises(ValueError, match="Invalid recipient email"):
        confirm_draft(
            session,
            draft.id,
            subject="AI research",
            body="Here is the research.",
            recipient="not-an-email",
            send_mail=fake_send_mail,
        )

    assert sent == []
    assert session.get(Draft, draft.id).state == "open"


def test_confirm_fails_when_draft_is_already_sent(session):
    draft = _open_draft(session)
    confirm_draft(
        session,
        draft.id,
        subject="AI research",
        body="Here is the research.",
        recipient="named@example.com",
        send_mail=lambda **kwargs: None,
    )

    with pytest.raises(DraftNotOpenError):
        confirm_draft(
            session,
            draft.id,
            subject="Again",
            body="Again",
            recipient="named@example.com",
            send_mail=lambda **kwargs: (_ for _ in ()).throw(AssertionError("SMTP")),
        )


def test_confirm_fails_when_draft_is_missing(session):
    with pytest.raises(DraftNotFoundError):
        confirm_draft(
            session,
            uuid.uuid4(),
            subject="AI research",
            body="Here is the research.",
            recipient="named@example.com",
            send_mail=lambda **kwargs: (_ for _ in ()).throw(AssertionError("SMTP")),
        )


def test_confirm_keeps_edited_open_draft_when_smtp_fails(session):
    draft = _open_draft(session)

    def boom(*, subject, content, to_email):
        raise RuntimeError("smtp down")

    with pytest.raises(RuntimeError, match="smtp down"):
        confirm_draft(
            session,
            draft.id,
            subject="Edited subject",
            body="Edited body",
            recipient="edited@example.com",
            send_mail=boom,
        )

    stored = session.get(Draft, draft.id)
    assert stored.state == "open"
    assert stored.subject == "Edited subject"
    assert stored.body == "Edited body"
    assert stored.recipient == "edited@example.com"


def test_chat_turn_payload_includes_text_and_structured_drafts(session):
    draft = _open_draft(session)

    payload = chat_turn_payload("Draft ready for review.", [draft])

    assert payload == {
        "content": "Draft ready for review.",
        "drafts": [
            {
                "id": str(draft.id),
                "subject": "AI research",
                "body": "Here is the research.",
                "recipient": "named@example.com",
                "state": "open",
            }
        ],
    }


def test_collecting_created_drafts_captures_only_this_turn(session):
    earlier = _open_draft(session, body="Earlier body")
    with collecting_created_drafts() as drafts:
        current = _open_draft(session, body="This turn")
    later = _open_draft(session, body="Later body")

    assert [item.id for item in drafts] == [current.id]
    assert earlier.id not in {item.id for item in drafts}
    assert later.id not in {item.id for item in drafts}


def test_discard_marks_draft_discarded_and_blocks_later_confirm(session):
    draft = _open_draft(session)
    discarded = discard_draft(session, draft.id)

    assert discarded.state == "discarded"
    assert session.get(Draft, draft.id).state == "discarded"

    with pytest.raises(DraftNotOpenError):
        confirm_draft(
            session,
            draft.id,
            subject="AI research",
            body="Here is the research.",
            recipient="named@example.com",
            send_mail=lambda **kwargs: (_ for _ in ()).throw(AssertionError("SMTP")),
        )


def test_list_open_drafts_omits_sent_and_discarded(session):
    open_draft = _open_draft(session, body="Still open")
    to_send = create_open_draft(
        session,
        subject="Will send",
        body="Sent body",
        pinned=None,
        named="sent@example.com",
        default="default@example.com",
    )
    to_discard = create_open_draft(
        session,
        subject="Will discard",
        body="Discard body",
        pinned=None,
        named="discard@example.com",
        default="default@example.com",
    )
    confirm_draft(
        session,
        to_send.id,
        subject="Will send",
        body="Sent body",
        recipient="sent@example.com",
        send_mail=lambda **kwargs: None,
    )
    discard_draft(session, to_discard.id)

    assert [item.id for item in list_open_drafts(session)] == [open_draft.id]


def test_multiple_drafts_are_confirmed_and_discarded_independently(session):
    first = create_open_draft(
        session,
        subject="First",
        body="First body",
        pinned=None,
        named="first@example.com",
        default="default@example.com",
    )
    second = create_open_draft(
        session,
        subject="Second",
        body="Second body",
        pinned=None,
        named="second@example.com",
        default="default@example.com",
    )
    sent: list[str] = []

    discard_draft(session, first.id)
    confirm_draft(
        session,
        second.id,
        subject="Second",
        body="Second body",
        recipient="second@example.com",
        send_mail=lambda **kwargs: sent.append(kwargs["to_email"]),
    )

    assert session.get(Draft, first.id).state == "discarded"
    assert session.get(Draft, second.id).state == "sent"
    assert sent == ["second@example.com"]


def test_discard_fails_when_draft_is_already_sent(session):
    draft = _open_draft(session)
    confirm_draft(
        session,
        draft.id,
        subject="AI research",
        body="Here is the research.",
        recipient="named@example.com",
        send_mail=lambda **kwargs: None,
    )

    with pytest.raises(DraftNotOpenError):
        discard_draft(session, draft.id)
