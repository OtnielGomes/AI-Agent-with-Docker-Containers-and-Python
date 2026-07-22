# Imports:
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

from api.ai.llms import get_openai_llm
from api.ai.tools import (
    send_me_email, 
    get_unread_emails,
    research_email
)

EMAIL_TOOLS_LIST = [
    send_me_email,
    get_unread_emails
]

def get_email_agent():
    model=get_openai_llm()
    agent = create_react_agent(
        model=model,
        tools=EMAIL_TOOLS_LIST,
        prompt="You are a helpful assistant for managing my email inbox for generating, sending and reviewing email.",
        name = "email_agent",
    )
    return agent

# agent.invoke({"message": "What is water?"}, config={"configurable": {"additional_field": "123"}})
def get_research_agent():
    model=get_openai_llm()
    agent = create_react_agent(
        model=model,
        tools=[research_email],
        prompt="You are a helpful research assistant for preparing email data.",
        name = "research_agent",
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
        prompt = (
            "You manage a research assistant and a"
            "email inbox manager assistant. Assign work to them."
        )
    ).compile()

    return supe