# imports 

import os
from contextlib import asynccontextmanager
from sys import prefix

from fastapi import FastAPI

from api.db import init_db
from api.chat.routing import router as chat_router
from api.chat.draft_routing import router as draft_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    # Before startup:
    init_db()
    yield
    # After startup:

# Create a fastapi app
app = FastAPI(lifespan=lifespan)
app.include_router(chat_router, prefix="/api/chats")
app.include_router(draft_router, prefix="/api/drafts")

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    raise NotImplementedError("API_KEY is not set")

MY_PROJECT = os.environ.get("MY_PROJECT") or "This is a default project"

# Create a route
@app.get("/")
def read_index():
    return {"Hello": "World",  "MY PROJECT NAME": MY_PROJECT}
