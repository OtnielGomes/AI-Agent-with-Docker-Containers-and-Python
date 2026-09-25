import pytest

from api.ai.outbound_email_body import (
    outbound_email_body_generation_hint,
    prepare_outbound_email_body,
)


def test_prepare_strips_seu_nome_placeholder_line():
    raw = "Here is the research.\n[Seu nome]"
    assert prepare_outbound_email_body(raw) == "Here is the research."


def test_prepare_removes_orphan_closing_left_by_placeholder():
    raw = "Segue o resumo da pesquisa.\n\nAbraço,\n[Seu nome]"
    assert prepare_outbound_email_body(raw) == "Segue o resumo da pesquisa."


@pytest.mark.parametrize(
    "placeholder",
    ["[Your name]", "[Nome]", "[Name]", "[Nome do remetente]"],
)
def test_prepare_strips_known_placeholder_names(placeholder):
    raw = f"Here is the research.\n{placeholder}"
    assert prepare_outbound_email_body(raw) == "Here is the research."


def test_prepare_drops_bracket_only_lines():
    raw = "Here is the research.\n[Something else]"
    assert prepare_outbound_email_body(raw) == "Here is the research."


def test_prepare_keeps_already_clean_body():
    raw = "Here is the research on AI.\n\nAbraço!"
    assert prepare_outbound_email_body(raw) == raw


def test_generation_hint_without_sender_name_forbids_placeholders_and_a_signature():
    hint = outbound_email_body_generation_hint("")
    assert "Meu Amor" in hint
    assert "[Seu nome]" in hint
    assert "[Your name]" in hint
    assert "[Nome]" in hint
    assert "Do not add a signature name." in hint
    assert "A configured sender name (none) is not written after the Closing." in hint


def test_generation_hint_with_sender_name_still_forbids_a_signature():
    hint = outbound_email_body_generation_hint("Maria Silva")
    assert "Do not add a signature name." in hint
    assert "A configured sender name (Maria Silva) is not written after the Closing." in hint
    assert "If you sign the email, use only this name" not in hint
