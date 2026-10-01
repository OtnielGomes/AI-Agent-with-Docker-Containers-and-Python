# imports:
import os

from langchain_core.callbacks import BaseCallbackHandler

from .llms import get_openai_llm
from .schemas import EmailMessageSchema
from .outbound_email_body import (
    outbound_email_body_generation_hint,
    prepare_outbound_email_body,
)
from .turn_usage import note_model_usage


def _email_composition_system_prompt() -> str:
    """Build system instructions for plain-text email generation."""
    sender_name = os.environ.get("EMAIL_SENDER_NAME", "").strip()
    return (
        "You are a helpful assistant for research and composing plain text emails. "
        "Do not use markdown — plain text only. "
        f"{outbound_email_body_generation_hint(sender_name)}"
    )


class _UsageHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[object] = []

    def on_chat_model_end(self, response, **kwargs) -> None:
        for group in getattr(response, "generations", ()) or ():
            for item in group:
                message = getattr(item, "message", None)
                if message is not None:
                    self.messages.append(message)


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

    handler = _UsageHandler()
    response = llm.invoke(messages, config={"callbacks": [handler]})
    note_model_usage(handler.messages)
    return EmailMessageSchema(
        subject=response.subject,
        contents=prepare_outbound_email_body(response.contents),
        invalid_request=response.invalid_request,
    )
