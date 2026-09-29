from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel

from api.db import get_session
from api.drafts import (
    DraftNotFoundError,
    DraftNotOpenError,
    confirm_draft,
    discard_draft,
    discard_open_drafts,
    draft_as_chat_item,
    list_open_drafts,
    list_prior_recipients,
)
from api.myemailer.sender import send_mail

router = APIRouter()


class ConfirmDraftPayload(SQLModel):
    subject: str
    body: str
    recipient: str


@router.get("/")
def get_open_drafts(session: Session = Depends(get_session)):
    return [draft_as_chat_item(draft) for draft in list_open_drafts(session)]


@router.get("/prior-recipients")
def get_prior_recipients(session: Session = Depends(get_session)):
    return list_prior_recipients(session)


@router.post("/discard-open")
def discard_every_open_draft(session: Session = Depends(get_session)):
    return [draft_as_chat_item(draft) for draft in discard_open_drafts(session)]


@router.post("/{draft_id}/confirm")
def confirm_open_draft(
    draft_id: UUID,
    payload: ConfirmDraftPayload,
    session: Session = Depends(get_session),
):
    try:
        draft = confirm_draft(
            session,
            draft_id,
            subject=payload.subject,
            body=payload.body,
            recipient=payload.recipient,
            send_mail=send_mail,
        )
    except DraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found.")
    except DraftNotOpenError:
        raise HTTPException(status_code=409, detail="Draft is not open.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return draft_as_chat_item(draft)


@router.post("/{draft_id}/discard")
def discard_open_draft(
    draft_id: UUID,
    session: Session = Depends(get_session),
):
    try:
        draft = discard_draft(session, draft_id)
    except DraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found.")
    except DraftNotOpenError:
        raise HTTPException(status_code=409, detail="Draft is not open.")
    return draft_as_chat_item(draft)
