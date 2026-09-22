# Imports:
import os

from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

from api.ai.llms import get_openai_llm
from api.ai.outbound_email_body import outbound_email_body_generation_hint
from api.ai.tools import (
    send_me_email,
    revise_email_draft,
    get_recent_emails,
    get_unread_emails,
    research_email,
)

EMAIL_TOOLS_LIST = [
    send_me_email,
    revise_email_draft,
    get_recent_emails,
    get_unread_emails,
]

_OPEN_DRAFT_RULES = (
    "The user message lists open Drafts on the review cards, oldest at the top. "
    "Position 1 is the first Draft and the top one. "
    "When the user asks to change an open Draft, call revise_email_draft. "
    "Do not call send_me_email for a change. "
    "If exactly one Draft is open, revise that Draft. "
    "If several are open, revise one only when the user identifies it by position, "
    "subject, or recipient. Otherwise ask which Draft, listing each subject and "
    "recipient in that order, in the language of the user's message, and do not "
    "create or revise a Draft. "
    "If none are open and the user asks to change an email, say there is nothing "
    "to revise, in the language of the user's message, and do not create a Draft. "
    "A request for a new email calls send_me_email and leaves open Drafts unchanged. "
    "One message may revise an identified Draft and create another when the user asks for both. "
    "Revise from the subject and body shown for that Draft, including edits on the card. "
    "Keep the Draft's language unless the user asks for another language. "
    "Pass to_email to revise_email_draft only when the user asked to change the Recipient. "
)

def get_email_agent():
    model = get_openai_llm()
    agent = create_react_agent(
        model=model,
        tools=EMAIL_TOOLS_LIST,
        prompt=(
            "You manage the user's email inbox. "
            "When asked to read, list, or summarize emails, always call get_recent_emails "
            "(use unread_only=True only when the user asks for unread mail). "
            "When asked to send a new email, call send_me_email. "
            f"{_OPEN_DRAFT_RULES}"
            "The UI may already set the recipient for a new email — in that case call "
            "send_me_email without to_email. If the user names a recipient in their message, "
            "pass it as to_email. If no recipient is configured and none was given, ask once "
            "for the Recipient address before creating a draft. "
            "A pinned recipient does not change a Draft that is already open. "
            "Never say you cannot access the inbox — use the available tools first. "
            "When calling send_me_email or revise_email_draft, pass clean plain-text body only: "
            "no markdown. "
            f"{outbound_email_body_generation_hint(os.environ.get('EMAIL_SENDER_NAME', ''))} "
            "After fetching emails, provide a clear summary or list as requested. "
            "Reply in the language of the user's message. "
            "After creating or revising a Draft, say the Draft is ready and name the Recipient. "
            "Do not offer extra tasks. Do not claim the email was sent."
        ),
        name="email_agent",
    )
    return agent

# agent.invoke({"message": "What is water?"}, config={"configurable": {"additional_field": "123"}})
def get_research_agent():
    model = get_openai_llm()
    agent = create_react_agent(
        model=model,
        tools=[research_email],
        prompt=(
            "You are a research assistant that prepares email-ready content. "
            "Use research_email for research requests and return clear subject and body text. "
            "The body must be plain text. "
            f"{outbound_email_body_generation_hint(os.environ.get('EMAIL_SENDER_NAME', ''))}"
        ),
        name="research_agent",
    )
    return agent


# supe = get_supervisor()
# supe.invoke({"messages": [{"role": "user", "content": "Find out how to create a latte then email me the results."}]})
def get_supervisor():
    llm = get_openai_llm()
    email_agent = get_email_agent()
    research_agent = get_research_agent()

    supe = create_supervisor(
        model=llm,
        agents=[email_agent, research_agent],
        prompt=(
            "You manage a research assistant and an email inbox manager. "
            "For requests to read, list, or summarize inbox emails, assign email_agent. "
            "For requests to change an open Draft, assign email_agent to revise it in place. "
            "Do not create a second Draft for a change. "
            "For a new email, assign email_agent to create a Draft with send_me_email "
            "and leave open Drafts unchanged. "
            "For requests like 'research and email me the results': "
            "1) assign research_agent to gather the content, "
            "2) assign email_agent to create a Draft with send_me_email. "
            "The user message lists open Drafts, oldest at the top. Position 1 is the first "
            "and the top one. If several are open, revise one only when the user identifies "
            "it by position, subject, or recipient. Otherwise ask which Draft, listing each "
            "subject and recipient in that order, in the language of the user's message, "
            "and change nothing. If none are open and the user asks to change an email, "
            "say there is nothing to revise and do not create a Draft. One message may "
            "revise an identified Draft and create another when the user asks for both. "
            "A revision keeps the Draft's language unless the user asks for another. "
            "The Recipient changes only when the user asks. "
            "The UI may pin an email recipient for a new email — respect that and do not "
            "ask for an address when it is already set. A pinned recipient does not change "
            "a Draft that is already open. "
            "Never stop after research to ask whether to continue — have email_agent "
            "create the draft. Do not claim mail was sent. "
            "Reply in the language of the user's message. After a Draft is created or revised, "
            "say it is ready and name the Recipient. Do not offer extra tasks. "
            "When a worker finishes, reply with its result directly — no transfer meta-commentary."
        ),
    ).compile()

    return supe