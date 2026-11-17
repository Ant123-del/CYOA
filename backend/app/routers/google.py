from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from .. import google_calendar as gcal
from ..auth import CurrentUser, current_user, get_user_settings
from ..config import get_settings

router = APIRouter(prefix="/api/google", tags=["google"])


@router.get("/auth-url")
def auth_url(user: CurrentUser = Depends(current_user)):
    try:
        return {"url": gcal.build_auth_url(user.uid, user.email)}
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/callback")
def callback(state: str = "", code: str = "", error: str = ""):
    """Google redirects here after consent (no Firebase token - identified by `state`)."""
    front = get_settings().app_url
    if error or not code:
        return RedirectResponse(f"{front}/settings?calendar=error&reason={error or 'missing_code'}")
    try:
        gcal.handle_callback(state, code)
    except Exception as exc:
        return RedirectResponse(f"{front}/settings?calendar=error&reason={type(exc).__name__}")
    return RedirectResponse(f"{front}/settings?calendar=connected")


@router.post("/disconnect")
def disconnect(user: CurrentUser = Depends(current_user)):
    gcal.disconnect(user.uid)
    return {"ok": True}


@router.get("/calendars")
def calendars(user: CurrentUser = Depends(current_user)):
    try:
        return gcal.list_calendars(user.uid)
    except gcal.CalendarNotConnected as exc:
        raise HTTPException(409, "Google Calendar is not connected") from exc


@router.get("/events")
def events(date: str, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    try:
        return gcal.list_events(user.uid, date, settings.timezone, settings.calendarId)
    except gcal.CalendarNotConnected as exc:
        raise HTTPException(409, "Google Calendar is not connected") from exc
