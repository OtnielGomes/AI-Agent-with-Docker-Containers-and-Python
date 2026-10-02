# imports:

import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session,select


from .models import (
    ChatMenssagePayload,
    ChatMessage,
    ChatMessage_listItem,
)
from api.db import get_session
from api.ai.agents import get_supervisor
from api.ai.schemas import SupervisorMessageSchema
from api.chat.turn import SupervisorTurnError, run_shared_turn
from api.drafts import chat_turn_payload
from api.myemailer.recipient import validated_recipient


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

@router.post("/", response_model=SupervisorMessageSchema)
def chat_create_message(
    payload: ChatMenssagePayload,
    session: Session = Depends(get_session)
    ):

    if payload.to_email is not None:
        try:
            pin = validated_recipient(payload.to_email)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_email address.")
    else:
        pin = None

    data = payload.model_dump(exclude={"to_email", "open_drafts", "inbound_emails"})
    obj = ChatMessage.model_validate(data)
    session.add(obj)
    session.commit()

    try:
        outcome = run_shared_turn(
            chat_message=payload.message,
            pinned_recipient=pin,
            open_drafts=payload.open_drafts,
            inbound_emails=payload.inbound_emails,
            session=session,
            default_inbox=os.environ.get("EMAIL_ADDRESS"),
            sender_name=os.environ.get("EMAIL_SENDER_NAME"),
            supervisor_factory=get_supervisor,
        )
    except SupervisorTurnError as exc:
        raise HTTPException(
            status_code=400, detail="Failed to get supervisor response"
        ) from exc
    return chat_turn_payload(
        outcome.assistant_reply,
        list(outcome.drafts),
        outcome.reply_targets,
        outcome.outcome,
        outcome.revision,
    )
