# Imports:
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from api.myemailer.sender import send_mail
from api.myemailer.inbox_reader import read_inbox
from api.ai.services import generate_email_message

@tool
def research_email(query:str):
    """
    Research an email based on a query.

    Args:
        query: The query to research.
    """
    #print(config)
    #metadata = config.get("metadata",)
    #add_field = metadata.get("additional_field")
    #print("add_field",add_field)
    response = generate_email_message(query)
    msg = f"Subject: {response.subject}:\nBody: {response.contents}"

    return msg

@tool
def send_me_email(subject:str, content:str) -> str:

    """
    Send an email to myself with a subject and content.

    Args:
        subject: The subject of the email.
        content: The content of the email.
    """
    try:
        send_mail(subject=subject, content=content)   
    except Exception as e:
        return f"Error sending email: {e}"
    return "Email sent successfully."


@tool
def get_unread_emails(hours_ago:int=48) -> str:
    """
    Get unread emails from the last 48 hours.

    Args:
        hours_ago: The number of hours ago to get unread emails from.
    """
    try:
        emails = read_inbox(hours_ago=hours_ago, verbose=False)
    except Exception as e:
        return f"Error getting unread emails: {e}"

    cleaned = []
    for email in emails:
        data = email.copy()
        if "html_body" in data:
            data.pop('html_body')
        msg = ""
        for k, v in data.items():
            msg += f"{k}:\t{v}"
        cleaned.append(msg)
    return "\n-----\n".join(cleaned)[:500]