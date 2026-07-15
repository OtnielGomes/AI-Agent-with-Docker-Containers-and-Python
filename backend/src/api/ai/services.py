# imports:
from .llms import get_openai_llm
from .schemas import EmailMessageSchema



def generate_email_message(query: str) -> EmailMessageSchema:
    llm_base = get_openai_llm()
    llm = llm_base.with_structured_output(EmailMessageSchema)

    messages = [
        (
            "system",
            "You are a helpful assistant for research and composing plain text emails.Do not use markdown in your response only plain text."
        ),
        ("human", f"{query}.Do not use markdown in your response only plain text."),
    ]

    return llm.invoke(messages)
