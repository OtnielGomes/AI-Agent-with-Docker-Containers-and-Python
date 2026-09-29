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
    discard_open_drafts,
    list_open_drafts,
    list_prior_recipients,
    revise_open_draft,
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


def test_create_drops_trailing_sender_name_and_placeholder(session):
    draft = create_open_draft(
        session,
        subject="Nota",
        body="Olá,\n\nSegue a nota.\n\nAté mais!\nMaria Silva\n[Seu nome]",
        pinned=None,
        named="named@example.com",
        default="default@example.com",
        sender_name="Maria Silva",
    )

    assert draft.body == "Olá,\n\nSegue a nota.\n\nAté mais!"


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


def test_confirm_keeps_a_human_typed_name_and_a_body_without_an_opening(session):
    draft = _open_draft(session)
    card_body = "Here is the note.\n\nTalk soon!\nOtniel Gomes"
    sent: list[dict] = []

    def fake_send_mail(*, subject, content, to_email):
        sent.append({"subject": subject, "content": content, "to_email": to_email})

    result = confirm_draft(
        session,
        draft.id,
        subject="A note",
        body=card_body,
        recipient="named@example.com",
        send_mail=fake_send_mail,
    )

    assert result.body == card_body
    assert sent == [
        {
            "subject": "A note",
            "content": card_body,
            "to_email": "named@example.com",
        }
    ]


def test_confirm_keeps_a_human_farewell(session):
    draft = _open_draft(session)
    card_body = "Here is the note.\n\nBest regards"
    sent: list[dict] = []

    def fake_send_mail(*, subject, content, to_email):
        sent.append({"subject": subject, "content": content, "to_email": to_email})

    result = confirm_draft(
        session,
        draft.id,
        subject="A note",
        body=card_body,
        recipient="named@example.com",
        send_mail=fake_send_mail,
    )

    assert result.body == card_body
    assert sent[0]["content"] == card_body


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


def _confirm(session, draft: Draft, *, subject: str, body: str, recipient: str) -> Draft:
    return confirm_draft(
        session,
        draft.id,
        subject=subject,
        body=body,
        recipient=recipient,
        send_mail=lambda **kwargs: None,
    )


def test_confirm_records_the_time_only_after_a_successful_send(session):
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

    failed = session.get(Draft, draft.id)
    assert failed.state == "open"
    assert failed.confirmed_at is None

    sent = _confirm(
        session,
        failed,
        subject="Edited subject",
        body="Edited body",
        recipient="edited@example.com",
    )
    assert sent.state == "sent"
    assert sent.confirmed_at is not None


def test_prior_recipients_are_sent_addresses_newest_confirm_first(session):
    older = create_open_draft(
        session,
        subject="Older",
        body="Older body",
        pinned=None,
        named="older@example.com",
        default="default@example.com",
    )
    newer = create_open_draft(
        session,
        subject="Newer",
        body="Newer body",
        pinned=None,
        named="newer@example.com",
        default="default@example.com",
    )
    _confirm(
        session,
        older,
        subject="Older",
        body="Older body",
        recipient="older@example.com",
    )
    _confirm(
        session,
        newer,
        subject="Newer",
        body="Newer body",
        recipient="newer@example.com",
    )

    assert list_prior_recipients(session) == [
        "newer@example.com",
        "older@example.com",
    ]


def test_prior_recipients_keep_one_address_using_the_latest_spelling(session):
    first = create_open_draft(
        session,
        subject="First",
        body="First body",
        pinned=None,
        named="Pat@Example.com",
        default="default@example.com",
    )
    second = create_open_draft(
        session,
        subject="Second",
        body="Second body",
        pinned=None,
        named="other@example.com",
        default="default@example.com",
    )
    _confirm(
        session,
        first,
        subject="First",
        body="First body",
        recipient="Pat@Example.com",
    )
    _confirm(
        session,
        second,
        subject="Second",
        body="Second body",
        recipient="pat@example.com",
    )

    assert list_prior_recipients(session) == ["pat@example.com"]


def test_prior_recipients_include_a_sent_address_with_no_confirm_time(session):
    dated = create_open_draft(
        session,
        subject="Dated",
        body="Dated body",
        pinned=None,
        named="dated@example.com",
        default="default@example.com",
    )
    _confirm(
        session,
        dated,
        subject="Dated",
        body="Dated body",
        recipient="dated@example.com",
    )
    legacy = Draft(
        subject="Legacy",
        body="Legacy body",
        recipient="legacy@example.com",
        state="sent",
    )
    session.add(legacy)
    session.commit()

    assert list_prior_recipients(session) == [
        "dated@example.com",
        "legacy@example.com",
    ]


def test_prior_recipients_omit_open_and_discarded_drafts(session):
    open_draft = _open_draft(session)
    discarded = create_open_draft(
        session,
        subject="Gone",
        body="Gone body",
        pinned=None,
        named="gone@example.com",
        default="default@example.com",
    )
    discard_draft(session, discarded.id)

    assert open_draft.state == "open"
    assert list_prior_recipients(session) == []


def test_discard_open_drafts_discards_every_open_draft_and_leaves_the_rest(session):
    first = _open_draft(session, body="First open")
    second = create_open_draft(
        session,
        subject="Second",
        body="Second open",
        pinned=None,
        named="second@example.com",
        default="default@example.com",
    )
    sent = create_open_draft(
        session,
        subject="Sent",
        body="Already sent",
        pinned=None,
        named="sent@example.com",
        default="default@example.com",
    )
    already_discarded = create_open_draft(
        session,
        subject="Discarded",
        body="Already discarded",
        pinned=None,
        named="old@example.com",
        default="default@example.com",
    )
    confirm_draft(
        session,
        sent.id,
        subject="Sent",
        body="Already sent",
        recipient="sent@example.com",
        send_mail=lambda **kwargs: None,
    )
    discard_draft(session, already_discarded.id)

    discarded = discard_open_drafts(session)

    assert {item.id for item in discarded} == {first.id, second.id}
    assert session.get(Draft, first.id).state == "discarded"
    assert session.get(Draft, second.id).state == "discarded"
    assert session.get(Draft, sent.id).state == "sent"
    assert session.get(Draft, already_discarded.id).state == "discarded"
    assert list_open_drafts(session) == []


def test_second_discard_open_drafts_finds_nothing_open(session):
    draft = _open_draft(session)
    discard_open_drafts(session)

    again = discard_open_drafts(session)

    assert again == []
    assert session.get(Draft, draft.id).state == "discarded"
    assert list_open_drafts(session) == []


def test_revise_updates_subject_and_body_and_keeps_id_open_state_and_recipient(session):
    draft = _open_draft(session)

    revised = revise_open_draft(
        session,
        draft.id,
        subject="Shorter subject",
        body="Shorter body.",
    )

    assert revised.id == draft.id
    assert revised.state == "open"
    assert revised.subject == "Shorter subject"
    assert revised.body == "Shorter body."
    assert revised.recipient == "named@example.com"
    stored = session.get(Draft, draft.id)
    assert stored.subject == "Shorter subject"
    assert stored.body == "Shorter body."
    assert stored.recipient == "named@example.com"
    assert stored.state == "open"


def test_revise_drops_trailing_sender_name_so_the_closing_is_last(session):
    draft = _open_draft(session)

    revised = revise_open_draft(
        session,
        draft.id,
        subject="Nota",
        body="Hello,\n\nThe note.\n\nTalk soon!\nMaria Silva",
        sender_name="Maria Silva",
    )

    assert revised.body == "Hello,\n\nThe note.\n\nTalk soon!"
    assert session.get(Draft, draft.id).body == "Hello,\n\nThe note.\n\nTalk soon!"


def test_revise_replaces_recipient_when_one_is_supplied(session):
    draft = _open_draft(session)

    revised = revise_open_draft(
        session,
        draft.id,
        subject="AI research",
        body="Here is the research.",
        recipient="new@example.com",
    )

    assert revised.recipient == "new@example.com"
    assert session.get(Draft, draft.id).recipient == "new@example.com"


def test_revise_rejects_invalid_recipient_and_creates_nothing(session):
    draft = _open_draft(session)

    with pytest.raises(ValueError, match="Invalid recipient email"):
        revise_open_draft(
            session,
            draft.id,
            subject="Changed",
            body="Changed body.",
            recipient="not-an-email",
        )

    stored = session.get(Draft, draft.id)
    assert stored.subject == "AI research"
    assert stored.body == "Here is the research."
    assert stored.recipient == "named@example.com"
    assert stored.state == "open"
    assert [item.id for item in session.exec(select(Draft)).all()] == [draft.id]


def test_revise_sent_or_discarded_or_missing_draft_changes_nothing(session):
    sent = _open_draft(session, body="Sent body")
    confirm_draft(
        session,
        sent.id,
        subject="AI research",
        body="Sent body",
        recipient="named@example.com",
        send_mail=lambda **kwargs: None,
    )
    discarded = create_open_draft(
        session,
        subject="Gone",
        body="Gone body",
        pinned=None,
        named="gone@example.com",
        default="default@example.com",
    )
    discard_draft(session, discarded.id)
    missing_id = uuid.uuid4()

    with pytest.raises(DraftNotOpenError):
        revise_open_draft(session, sent.id, subject="Nope", body="Nope")
    with pytest.raises(DraftNotOpenError):
        revise_open_draft(session, discarded.id, subject="Nope", body="Nope")
    with pytest.raises(DraftNotFoundError):
        revise_open_draft(session, missing_id, subject="Nope", body="Nope")

    assert session.get(Draft, sent.id).subject == "AI research"
    assert session.get(Draft, sent.id).state == "sent"
    assert session.get(Draft, discarded.id).subject == "Gone"
    assert session.get(Draft, discarded.id).state == "discarded"
    assert session.get(Draft, missing_id) is None
    assert len(session.exec(select(Draft)).all()) == 2


def test_revise_is_returned_with_the_turn_drafts(session):
    draft = _open_draft(session)
    with collecting_created_drafts() as drafts:
        revise_open_draft(
            session,
            draft.id,
            subject="Short",
            body="Short body.",
        )

    assert [item.id for item in drafts] == [draft.id]
    assert drafts[0].subject == "Short"
    assert drafts[0].body == "Short body."
    assert drafts[0].state == "open"


def test_revise_replaces_a_draft_created_in_the_same_turn(session):
    with collecting_created_drafts() as drafts:
        created = create_open_draft(
            session,
            subject="Original",
            body="Original body",
            pinned=None,
            named="named@example.com",
            default="default@example.com",
        )
        revise_open_draft(
            session,
            created.id,
            subject="Revised",
            body="Revised body.",
        )

    assert [item.id for item in drafts] == [created.id]
    assert drafts[0].subject == "Revised"
    assert drafts[0].body == "Revised body."


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
