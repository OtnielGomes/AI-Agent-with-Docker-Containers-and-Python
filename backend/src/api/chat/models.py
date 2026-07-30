# imports:

from email.policy import default
from sqlmodel import SQLModel, Field, DateTime
from datetime import datetime, timezone

def get_utc_now():
    return datetime.now().replace(tzinfo=timezone.utc)

# Validation
class ChatMenssagePayload(SQLModel):
    message: str
    to_email: str | None = None

# Saving, getting,updating, deleting:
class ChatMessage(SQLModel, table=True):
    
    id: int | None = Field(default=None, primary_key=True)
    message: str
    created_at: datetime = Field(
        default_factory=get_utc_now,
        sa_type=DateTime(timezone=True), # SQLAlchemy type
        primary_key=False,
        nullable=False,
    )

# Invoke-RestMethod -Method GET -Uri "http://localhost:8080/api/chats/recent/"
class ChatMessage_listItem(SQLModel):

    id: int | None = Field(default=None)
    message: str
    created_at: datetime = Field(default = None)