import pytest

from api.inbound_mail import (
    compose_reply,
    html_to_text,
    reply_opening,
    reply_subject,
    split_sender,
    to_inbound_item,
)


def test_reply_subject_adds_one_re_and_collapses_extras():
    assert reply_subject("Reunião") == "Re: Reunião"
    assert reply_subject("Re: Reunião") == "Re: Reunião"
    assert reply_subject("RE: Re: Reunião") == "Re: Reunião"
    assert reply_subject("   ") == "Re:"
    assert reply_subject(None) == "Re:"


def test_split_sender_keeps_a_display_name_and_drops_an_address_used_as_a_name():
    assert split_sender("Maria Silva <maria@example.com>") == (
        "Maria Silva",
        "maria@example.com",
    )
    assert split_sender("maria@example.com") == (None, "maria@example.com")


def test_html_only_email_becomes_plain_text_without_tags():
    item = to_inbound_item(
        {
            "uid": "15",
            "from": "Maria Silva <maria@example.com>",
            "subject": "Olá",
            "timestamp": "Fri, 25 Sep 2026 10:00:00 +0000",
            "unread": True,
            "html_body": "<p>Olá <b>mundo</b></p><script>alert(1)</script>",
        }
    )
    assert item is not None
    assert item["body"] == "Olá mundo"
    assert "<b>" not in item["body"]
    assert "alert" not in item["body"]
    assert item["sender"] == "Maria Silva"
    assert item["unread"] is True
    assert html_to_text("<p>A &amp; B</p>") == "A & B"


def test_reply_opening_uses_the_sender_name_and_does_not_invent_one():
    assert reply_opening("Maria", "pt") == "Olá, Maria,"
    assert reply_opening(None, "pt") == "Olá,"
    assert reply_opening("Ann", "en") == "Hello, Ann,"
    assert reply_opening(None, "en") == "Hello,"


def test_compose_reply_answers_without_quoting_and_ignores_any_pin():
    def generate(instruction: str) -> str:
        assert "SECRET-QUOTE" in instruction
        assert "pin@" not in instruction
        return "Posso na quinta."

    reply = compose_reply(
        {
            "sender": "Maria Silva",
            "address": "maria@example.com",
            "subject": "Re: Reunião",
            "body": "SECRET-QUOTE sobre a reunião.",
        },
        generate,
    )

    assert reply["recipient"] == "maria@example.com"
    assert reply["subject"] == "Re: Reunião"
    assert reply["body"].startswith("Olá, Maria Silva,")
    assert "Posso na quinta." in reply["body"]
    assert reply["body"].endswith("Até mais!")
    assert "SECRET-QUOTE" not in reply["body"]


def test_compose_reply_uses_english_and_falls_back_to_portuguese():
    english = compose_reply(
        {
            "sender": "Ann",
            "address": "ann@example.com",
            "subject": "Meeting",
            "body": "Please send the report and thanks.",
        },
        lambda _instruction: "Friday works.",
    )
    assert english["body"].startswith("Hello, Ann,")
    assert english["body"].endswith("Talk soon!")

    unknown = compose_reply(
        {
            "sender": "ann@example.com",
            "address": "ann@example.com",
            "subject": "",
            "body": "",
        },
        lambda instruction: "ok" if "answer from the subject" in instruction else "",
    )
    assert unknown["subject"] == "Re:"
    assert unknown["body"].startswith("Olá,")
    assert "Hello," not in unknown["body"].splitlines()[0]
    assert unknown["body"].endswith("Até mais!")


def test_compose_reply_rejects_an_invalid_sender_before_generating():
    called = False

    def generate(_instruction: str) -> str:
        nonlocal called
        called = True
        return "não deve"

    with pytest.raises(ValueError):
        compose_reply(
            {"sender": "nope", "address": "nope", "subject": "Oi", "body": "Texto"},
            generate,
        )
    assert called is False
