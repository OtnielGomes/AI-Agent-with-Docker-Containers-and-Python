# imports:
import os

from .llms import get_openai_llm
from .schemas import EmailMessageSchema
from .email_sanitize import sanitize_email_body


def _email_composition_system_prompt() -> str:
    """Build system instructions for plain-text email generation."""
    sender_name = os.environ.get("EMAIL_SENDER_NAME", "").strip()
    if sender_name:
        signing_rule = (
            f"If you sign the email, use only this name: {sender_name}. "
        )
    else:
        signing_rule = (
            "Do not add a signature name unless the user explicitly provides one. "
        )

    return (
        "You are a helpful assistant for research and composing plain text emails. "
        "Match the user's language (use Brazilian Portuguese when they write in Portuguese). "
        "Do not use markdown — plain text only. "
        "Never use placeholders such as [Seu nome], [Your name], [Nome], or similar. "
        f"{signing_rule}"
        "End informational emails on the last useful paragraph, or with a brief natural "
        "closing (e.g. 'Abraço!' or 'Até mais!'). "
        "Never end with 'Abraço,' followed by a name placeholder on the next line."
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
        contents=sanitize_email_body(response.contents),
        invalid_request=response.invalid_request,
    )
