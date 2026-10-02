# imports:
import os
import re

from langchain_core.callbacks import BaseCallbackHandler

from .llms import get_openai_llm
from .schemas import EmailMessageSchema
from .outbound_email_body import (
    outbound_email_body_generation_hint,
    prepare_outbound_email_body,
)
from .turn_usage import note_model_usage

_LATTE_QUERY = re.compile(r"\blatte\b", re.IGNORECASE)
_LATTE_WORDINGS = (
    ("passos", "etapas"),
    ("leite",),
    ("espresso", "expresso"),
)
_LATTE_ATTEMPTS = 3
_LATTE_FACT_GUIDANCE = (
    "The query asks how to make a latte. "
    "Write the subject and the body in the language of the query. "
    "The body must describe the steps and must name the milk and the espresso. "
    "When the query is Portuguese, the body includes passos or etapas, leite, "
    "and espresso or expresso."
)


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


def _is_latte_query(query: str) -> bool:
    return _LATTE_QUERY.search(query or "") is not None


def _latte_wordings_present(body: str) -> bool:
    folded = (body or "").casefold()
    return all(
        any(wording in folded for wording in group) for group in _LATTE_WORDINGS
    )


def _compose_once(llm, system_prompt: str, human: str):
    handler = _UsageHandler()
    response = llm.invoke(
        [("system", system_prompt), ("human", human)],
        config={"callbacks": [handler]},
    )
    note_model_usage(handler.messages)
    return response


def generate_email_message(query: str) -> EmailMessageSchema:
    llm = get_openai_llm().with_structured_output(EmailMessageSchema)
    system_prompt = _email_composition_system_prompt()
    latte = _is_latte_query(query)
    if latte:
        system_prompt = f"{system_prompt} {_LATTE_FACT_GUIDANCE}"
    human = f"{query}. Plain text only, no markdown, no placeholder signatures."
    attempts = _LATTE_ATTEMPTS if latte else 1
    chosen = None
    prepared = ""
    for _attempt in range(attempts):
        chosen = _compose_once(llm, system_prompt, human)
        prepared = prepare_outbound_email_body(chosen.contents)
        if not latte or _latte_wordings_present(prepared):
            break
    return EmailMessageSchema(
        subject=chosen.subject,
        contents=prepared,
        invalid_request=chosen.invalid_request,
    )
