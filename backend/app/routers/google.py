from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import google_calendar as gcal
from ..auth import CurrentUser, current_user, get_user_settings

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class LinkIn(BaseModel):
    calendarId: str = Field(max_length=2048)  # may be a pasted URL; validated server-side


class CalendarPatch(BaseModel):
    isDefault: bool | None = None
    readEnabled: bool | None = None
    readOnly: bool | None = None  # "never let CYOA edit this calendar"


@router.get("")
def calendar_info(user: CurrentUser = Depends(current_user)):
    return gcal.info(user.uid)


@router.post("/link")
def link(body: LinkIn, user: CurrentUser = Depends(current_user)):
    """Link (another) shared calendar. Returns "linked", or "verify" with a code to prove ownership."""
    get_user_settings(user)  # ensure the user doc exists
    try:
        return gcal.link_calendar(user.uid, user.email, user.email_verified, body.calendarId)
    except gcal.CalendarLinkError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/{key}")
def update(key: str, body: CalendarPatch, user: CurrentUser = Depends(current_user)):
    """Make a calendar the default for new events, or include/exclude it from planning."""
    if body.isDefault is False:
        raise HTTPException(400, "Choose another calendar as the default instead.")
    try:
        gcal.update_calendar(
            user.uid, key, is_default=body.isDefault, read_enabled=body.readEnabled, read_only=body.readOnly
        )
    except gcal.CalendarLinkError as exc:
        raise HTTPException(400, str(exc)) from exc
    except gcal.CalendarNotConnected as exc:
        raise HTTPException(404, "Calendar not linked") from exc
    return gcal.info(user.uid)


@router.delete("/{key}")
def remove(key: str, user: CurrentUser = Depends(current_user)):
    if not any(c["key"] == key for c in gcal.linked_calendars(user.uid)):
        raise HTTPException(404, "Calendar not linked")
    gcal.unlink_calendar(user.uid, key)
    return gcal.info(user.uid)


@router.post("/unlink")
def unlink_all(user: CurrentUser = Depends(current_user)):
    gcal.unlink_all(user.uid)
    return {"ok": True}


@router.get("/events")
def events(date: str, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    try:
        return gcal.list_events(user.uid, date, settings.timezone)
    except gcal.CalendarNotConnected as exc:
        raise HTTPException(409, "No Google Calendar linked") from exc
