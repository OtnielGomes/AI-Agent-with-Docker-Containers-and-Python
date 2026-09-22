# imports:

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session,select


from .models import (
    ChatMenssagePayload,
    ChatMessage,
    ChatMessage_listItem,
    OpenDraftSnapshot,
)
from api.db import get_session
from api.ai.agents import get_supervisor
from api.ai.messages import extract_assistant_reply
from api.ai.schemas import SupervisorMessageSchema
from api.drafts import chat_turn_payload, collecting_created_drafts
from api.myemailer.recipient import validated_recipient

def _with_open_drafts(message: str, open_drafts: list[OpenDraftSnapshot]) -> str:
    """Give the model the review cards for this turn, oldest first."""
    if not open_drafts:
        return f"{message}\n\nOpen Drafts on the review cards: none."

    blocks: list[str] = []
    for index, draft in enumerate(open_drafts, start=1):
        blocks.append(
            f"{index}. id: {draft.id}\n"
            f"subject: {draft.subject}\n"
            f"recipient: {draft.recipient}\n"
            f"body:\n{draft.body}"
        )
    listed = "\n\n".join(blocks)
    return (
        f"{message}\n\n"
        "Open Drafts on the review cards, oldest at the top:\n\n"
        f"{listed}"
    )


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

    data = payload.model_dump(exclude={"to_email", "open_drafts"})
    obj = ChatMessage.model_validate(data)
    session.add(obj)
    session.commit()

    supe = get_supervisor()
    msg_data = {
        "messages": [
            {
                "role": "user",
                "content": _with_open_drafts(payload.message, payload.open_drafts),
            },
        ]
    }
    invoke_config = None
    if pin:
        invoke_config = {"configurable": {"to_email": pin}}

    with collecting_created_drafts() as drafts:
        result = supe.invoke(msg_data, config=invoke_config)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to get supervisor response")
    
    messages = result.get("messages")
    if not messages:
        raise HTTPException(status_code=400, detail="Failed to get supervisor response")
    
    return chat_turn_payload(extract_assistant_reply(messages), drafts)
