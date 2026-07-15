# imports:

import os

from pydantic import BaseModel, Field

class EmailMessageSchema(BaseModel):
    subject: str
    contents: str