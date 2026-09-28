import re

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


_INVISIBLE = "\u034f\u200c\ufeff\u2007\u00ad\u200b"

_QUOTED_PLAIN = """Em qui., 24 de set. de 2026, 22:58, Caroline Salles <sallesc31@gmail.com>
escreveu:

> Pilantra
>
>> Eu banho
>>
>>> Queria te contar alguns benefícios de tomar banho todos os dias. Isso
>>> ajuda a manter a pele mais limpa.
"""

_QUOTED_HTML = """
<div>Em qui., 24 de set. de 2026, 22:58, Caroline Salles &lt;sallesc31@gmail.com&gt; escreveu:</div>
<blockquote><div>Pilantra</div>
<blockquote><div>Eu banho</div>
<blockquote><div>Queria te contar alguns benefícios de tomar banho todos os dias. Isso ajuda a manter a pele mais limpa.</div>
</blockquote></blockquote></blockquote>
"""

_NEWSLETTER_PLAIN = (
    f"PREHEADER_SECRET {_INVISIBLE}\n"
    "Expand your career opportunities                                                                                                      "
    "Build on your skills with additional training.\n"
    "GoogleGoogle Digital Marketing & E-commerceEnroll now\n"
    "-->\n"
)

_NEWSLETTER_HTML = f"""
<html><head><style>.pad {{ padding: 40px; }}</style></head><body>
<div style="display:none;max-height:0;overflow:hidden">PREHEADER_SECRET {_INVISIBLE}</div>
<!--[if mso]><table><tr><td><![endif]-->
<h1>Expand your career opportunities</h1>
<p>Build on your skills with additional training.</p>
<table><tr>
<td>Google</td>
<td><a href="https://www.coursera.org/learn/x">Google Digital Marketing &amp; E-commerce</a></td>
<td><a href="https://www.coursera.org/enroll">Enroll now</a></td>
</tr></table>
</body></html>
"""


def _assert_readable_reply(body: str) -> None:
    assert "Pilantra" in body
    assert "Eu banho" in body
    assert "Isso ajuda a manter a pele mais limpa" in body
    assert "PilantraEu" not in body
    assert "escreveu:Pilantra" not in body
    assert not any(line.lstrip().startswith(">") for line in body.splitlines())


def _assert_readable_newsletter(body: str) -> None:
    assert "Expand your career opportunities" in body
    assert "opportunitiesBuild" not in body
    assert "Build on your skills with additional training." in body
    assert "Google Digital Marketing & E-commerce" in body
    assert re.search(r"E-commerce\s+Enroll now", body)
    assert "PREHEADER_SECRET" not in body
    assert "-->" not in body
    assert "GoogleGoogle" not in body
    assert not any(char in body for char in _INVISIBLE)
    assert not re.search(r" {3,}", body)


def test_quoted_reply_body_is_readable_plain_text():
    multipart = to_inbound_item(
        {
            "uid": "24",
            "from": "Caroline Salles <sallesc31@gmail.com>",
            "subject": "Re: Benefícios de tomar banho todos os dias",
            "timestamp": "Thu, 24 Sep 2026 22:59:28 -0300",
            "body": _QUOTED_PLAIN,
            "html_body": _QUOTED_HTML,
        }
    )
    plain_only = to_inbound_item(
        {
            "uid": "25",
            "from": "Caroline Salles <sallesc31@gmail.com>",
            "subject": "Re: Benefícios de tomar banho todos os dias",
            "timestamp": "Thu, 24 Sep 2026 22:59:28 -0300",
            "body": _QUOTED_PLAIN,
        }
    )
    assert multipart is not None and plain_only is not None
    _assert_readable_reply(multipart["body"])
    _assert_readable_reply(plain_only["body"])


def test_newsletter_body_is_readable_plain_text():
    multipart = to_inbound_item(
        {
            "uid": "22",
            "from": "Coursera <no-reply@coursera.org>",
            "subject": "Learn from Google, IBM, Meta, and more",
            "timestamp": "Tue, 22 Sep 2026 21:46:36 +0000",
            "body": _NEWSLETTER_PLAIN,
            "html_body": _NEWSLETTER_HTML,
        }
    )
    html_only = to_inbound_item(
        {
            "uid": "23",
            "from": "Coursera <no-reply@coursera.org>",
            "subject": "Learn from Google, IBM, Meta, and more",
            "timestamp": "Tue, 22 Sep 2026 21:46:36 +0000",
            "html_body": _NEWSLETTER_HTML,
        }
    )
    assert multipart is not None and html_only is not None
    _assert_readable_newsletter(multipart["body"])
    _assert_readable_newsletter(html_only["body"])


def test_plain_email_keeps_short_lines_and_image_only_html_falls_back():
    plain = to_inbound_item(
        {
            "uid": "3",
            "from": "Maria Silva <maria@example.com>",
            "subject": "Oi",
            "body": "Olá,\n\nTexto curto.\n\nAté mais!",
        }
    )
    fallback = to_inbound_item(
        {
            "uid": "9",
            "from": "Maria Silva <maria@example.com>",
            "subject": "Foto",
            "body": "Texto que importa.",
            "html_body": "<html><body><img src='x' alt='foto'></body></html>",
        }
    )
    assert plain is not None and fallback is not None
    assert plain["body"] == "Olá,\n\nTexto curto.\n\nAté mais!"
    assert fallback["body"] == "Texto que importa."


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
