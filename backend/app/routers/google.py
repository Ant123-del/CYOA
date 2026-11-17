from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import google_calendar as gcal
from ..auth import CurrentUser, current_user, get_user_settings

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class LinkIn(BaseModel):
    calendarId: str = Field(max_length=2048)  # may be a pasted URL; validated server-side


@router.get("")
def calendar_info(user: CurrentUser = Depends(current_user)):
    return gcal.info(user.uid)


@router.post("/link")
def link(body: LinkIn, user: CurrentUser = Depends(current_user)):
    """Link a shared calendar. Returns status "linked", or "verify" with a code to prove ownership."""
    get_user_settings(user)  # ensure the user doc exists
    try:
        return gcal.link_calendar(user.uid, user.email, user.email_verified, body.calendarId)
    except gcal.CalendarLinkError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/unlink")
def unlink(user: CurrentUser = Depends(current_user)):
    gcal.unlink(user.uid)
    return {"ok": True}


@router.get("/events")
def events(date: str, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    try:
        return gcal.list_events(user.uid, date, settings.timezone)
    except gcal.CalendarNotConnected as exc:
        raise HTTPException(409, "No Google Calendar linked") from exc
