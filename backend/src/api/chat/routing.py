# imports:

from typing import List
from fastapi import APIRouter, Depends
from sqlmodel import Session,select

from .models import ChatMenssagePayload, ChatMessage, ChatMessage_listItem
from api.db import get_session

# Router:
router = APIRouter()

# API/chats
@router.get("/")
def chat_health():
    return {"status": "ok"}

# api/chats/recent/
# curl -X GET http://localhost:8080/api/chats/recent/
# Invoke-RestMethod -Method GET -Uri "http://localhost:8080/api/chats/recent/"
@router.get("/recent/", response_model=List[ChatMessage_listItem])
def chat_list_messages(session: Session = Depends(get_session)):

    query = select(ChatMessage) # sql -> query
    results = session.exec(query).fetchall()[:10]
    return results

# HTTP POST -> payload = {"message": "Hello, world!"} -> {message: "Hello, world!", "id": 1}
# curl -X POST -d '{"message": "Hello, world!"} -H 'Content-Type: application/json' http://localhost:8080/api/chats/
# Invoke-RestMethod -Method POST -Uri "http://localhost:8080/api/chats/" -ContentType "application/json" -Body '{"message": "Hello, world!"}'
# Invoke-RestMethod -Method POST -Uri "http://localhost:8080/api/chats/" -ContentType "application/json" -Body '{"message": "Hello, world!"}'
@router.post("/", response_model=ChatMessage)
def chat_create_message(
    payload: ChatMenssagePayload,
    session: Session = Depends(get_session)
    ):

    data = payload.model_dump() # pydantic -> dict
    print(data)

    obj = ChatMessage.model_validate(data)
    # ready to store in the database
    session.add(obj)
    session.commit()
    session.refresh(obj) # ensure id/primary key add to the object instance

    return obj