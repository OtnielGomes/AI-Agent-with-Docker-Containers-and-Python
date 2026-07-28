import os
from api.myemailer.gmail_imap_parser import GmailImapParser 

EMAIL_ADDRESS=os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD=os.environ.get("EMAIL_PASSWORD")


def read_inbox(
    hours_ago: int = 24,
    unread_only: bool = True,
    limit: int | None = None,
    verbose: bool = False,
) -> list[dict]:
    """Fetch inbox emails, optionally filtered and limited to the most recent."""
    parser = GmailImapParser(
        email_address=EMAIL_ADDRESS,
        app_password=EMAIL_PASSWORD,
    )

    emails = parser.fetch_emails(hours=hours_ago, unread_only=unread_only)

    try:
        emails.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    except TypeError:
        pass

    if limit is not None:
        emails = emails[:limit]

    if verbose:
        for email in emails:
            print(f"From: {email['from']}")
            print(f"Subject: {email['subject']}")
            print(f"Date: {email['timestamp']}")
            print("---")
    return emails

