# imports:

from typing import List
from fastapi import APIRouter, Depends
from sqlmodel import Session,select

from .models import ChatMenssagePayload, ChatMessage, ChatMessage_listItem
from api.db import get_session
from api.ai.services import generate_email_message
from api.ai.schemas import EmailMessageSchema

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
# curl -X POST -d '{"message": "Give me a summary of why it is good to go  outside."} -H "Content-Type: application/json" http://localhost:8080/api/chats/
# Invoke-RestMethod -Method POST -Uri "http://localhost:8080/api/chats/" -ContentType "application/json" -Body '{"message": "Give me asummary of why it is good to go  outside."}'

#$body = '{"message": "Give me a summary of why it is good to go outside."}'

#Invoke-RestMethod `
#  -Method POST `
#  -Uri "http://localhost:8080/api/chats/" `
#  -ContentType "application/json" `
#  -Body $body

@router.post("/", response_model=EmailMessageSchema)
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
    #session.refresh(obj) # ensure id/primary key add to the object instance

    response = generate_email_message(payload.message)
    return response