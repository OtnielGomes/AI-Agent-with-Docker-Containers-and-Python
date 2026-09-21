# imports:

import os

from pydantic import BaseModel, Field

class EmailMessageSchema(BaseModel):
    subject: str
    contents: str
    invalid_request: bool | None = Field(default=False)


class DraftSchema(BaseModel):
    id: str
    subject: str
    body: str
    recipient: str
    state: str


class SupervisorMessageSchema(BaseModel):
    content: str
    drafts: list[DraftSchema] = Field(default_factory=list)