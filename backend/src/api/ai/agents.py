# Imports:
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

from api.ai.llms import get_openai_llm
from api.ai.tools import (
    send_me_email,
    get_recent_emails,
    get_unread_emails,
    research_email,
)

EMAIL_TOOLS_LIST = [
    send_me_email,
    get_recent_emails,
    get_unread_emails,
]

def get_email_agent():
    model = get_openai_llm()
    agent = create_react_agent(
        model=model,
        tools=EMAIL_TOOLS_LIST,
        prompt=(
            "You manage the user's email inbox. "
            "When asked to read, list, or summarize emails, always call get_recent_emails "
            "(use unread_only=True only when the user asks for unread mail). "
            "When asked to send or email results, always call send_me_email. "
            "Never say you cannot access the inbox — use the available tools first. "
            "Never ask for an email address — the destination is already configured. "
            "Never ask for confirmation before sending. "
            "After fetching emails, provide a clear summary or list as requested. "
            "After sending, briefly confirm success."
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
            "Use research_email for research requests and return clear subject and body text."
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
            "For requests like 'research and email me the results': "
            "1) assign research_agent to gather the content, "
            "2) assign email_agent to send it with send_me_email. "
            "Never ask the user for an email address. "
            "Never stop after research to ask for confirmation — complete the send. "
            "When a worker finishes, reply with its result directly — no transfer meta-commentary."
        ),
    ).compile()

    return supe