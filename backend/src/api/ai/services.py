# imports:
import os

from .llms import get_openai_llm
from .schemas import EmailMessageSchema
from .outbound_email_body import (
    outbound_email_body_generation_hint,
    prepare_outbound_email_body,
)


def _email_composition_system_prompt() -> str:
    """Build system instructions for plain-text email generation."""
    sender_name = os.environ.get("EMAIL_SENDER_NAME", "").strip()
    return (
        "You are a helpful assistant for research and composing plain text emails. "
        "Match the user's language (use Brazilian Portuguese when they write in Portuguese). "
        "Do not use markdown — plain text only. "
        f"{outbound_email_body_generation_hint(sender_name)}"
    )


def generate_email_message(query: str) -> EmailMessageSchema:
    llm_base = get_openai_llm()
    llm = llm_base.with_structured_output(EmailMessageSchema)

    system_prompt = _email_composition_system_prompt()
    messages = [
        ("system", system_prompt),
        (
            "human",
            f"{query}. Plain text only, no markdown, no placeholder signatures.",
        ),
    ]

    response = llm.invoke(messages)
    return EmailMessageSchema(
        subject=response.subject,
        contents=prepare_outbound_email_body(response.contents),
        invalid_request=response.invalid_request,
    )
