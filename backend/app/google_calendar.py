"""Google OAuth (offline access) + Google Calendar helpers.

Sign-in uses Firebase Auth on the frontend. Calendar access is a separate
"Connect Google Calendar" step so the backend gets a *refresh token* and can
add events / read the schedule even when the user isn't on the site.
"""

import logging
import os
from datetime import datetime, timedelta

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import get_settings
from .firebase import db, user_ref
from .timeutil import day_bounds, new_id, now_iso, tz

log = logging.getLogger("cyoa.calendar")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Google may return extra scopes (openid, email) - don't treat that as an error.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
if get_settings().backend_url.startswith("http://localhost"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # local dev only


class CalendarNotConnected(Exception):
    pass


def _client_config() -> dict:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in backend/.env")
    return {
        "web": {
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [s.google_redirect_uri],
        }
    }


def _private_ref(uid: str):
    return user_ref(uid).collection("private").document("google")


# ---------- OAuth flow ----------


def build_auth_url(uid: str, login_hint: str = "") -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=get_settings().google_redirect_uri)
    state = new_id() + new_id()
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # always return a refresh token
        include_granted_scopes="true",
        state=state,
        login_hint=login_hint or None,
    )
    db().collection("oauth_states").document(state).set(
        {"uid": uid, "codeVerifier": flow.code_verifier, "createdAt": now_iso()}
    )
    return url


def handle_callback(state: str, code: str) -> str:
    """Exchange the code for tokens and store the refresh token. Returns uid."""
    state_ref = db().collection("oauth_states").document(state)
    snap = state_ref.get()
    if not snap.exists:
        raise ValueError("Unknown or expired OAuth state")
    data = snap.to_dict()
    state_ref.delete()

    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=get_settings().google_redirect_uri,
        state=state,
        code_verifier=data.get("codeVerifier"),
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    uid = data["uid"]
    if creds.refresh_token:
        _private_ref(uid).set({"refreshToken": creds.refresh_token, "scopes": list(creds.scopes or SCOPES)})
    user_ref(uid).set({"googleConnected": True}, merge=True)
    return uid


def disconnect(uid: str) -> None:
    snap = _private_ref(uid).get()
    if snap.exists:
        token = (snap.to_dict() or {}).get("refreshToken")
        if token:
            try:
                import urllib.request

                urllib.request.urlopen(
                    urllib.request.Request(
                        f"https://oauth2.googleapis.com/revoke?token={token}",
                        method="POST",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    ),
                    timeout=10,
                )
            except Exception:  # best effort
                pass
        _private_ref(uid).delete()
    user_ref(uid).set({"googleConnected": False}, merge=True)


# ---------- Calendar API ----------


def _service(uid: str):
    snap = _private_ref(uid).get()
    if not snap.exists:
        raise CalendarNotConnected()
    s = get_settings()
    creds = Credentials(
        token=None,
        refresh_token=snap.to_dict()["refreshToken"],
        token_uri=TOKEN_URI,
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        log.warning("Refresh token for %s no longer valid: %s", uid, exc)
        _private_ref(uid).delete()
        user_ref(uid).set({"googleConnected": False}, merge=True)
        raise CalendarNotConnected() from exc
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def is_connected(uid: str) -> bool:
    return _private_ref(uid).get().exists


def list_calendars(uid: str) -> list[dict]:
    items = _service(uid).calendarList().list(minAccessRole="writer").execute().get("items", [])
    return [
        {"id": c["id"], "summary": c.get("summaryOverride") or c.get("summary", c["id"]), "primary": c.get("primary", False)}
        for c in items
    ]


def list_events(uid: str, day: str, tz_name: str, calendar_id: str = "primary") -> list[dict]:
    start, end = day_bounds(day, tz_name)
    resp = (
        _service(uid)
        .events()
        .list(
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )
    zone = tz(tz_name)
    out = []
    for ev in resp.get("items", []):
        if ev.get("status") == "cancelled":
            continue
        s, e = ev.get("start", {}), ev.get("end", {})
        all_day = "date" in s and "dateTime" not in s
        if all_day:
            start_hm, end_hm = "00:00", "23:59"
        else:
            sd = datetime.fromisoformat(s["dateTime"]).astimezone(zone)
            ed = datetime.fromisoformat(e["dateTime"]).astimezone(zone)
            start_hm, end_hm = sd.strftime("%H:%M"), ed.strftime("%H:%M")
        out.append(
            {
                "id": ev["id"],
                "summary": ev.get("summary", "(no title)"),
                "description": (ev.get("description") or "")[:500],
                "start": start_hm,
                "end": end_hm,
                "allDay": all_day,
                "createdByCyoa": (ev.get("extendedProperties", {}).get("private", {}).get("cyoa") == "1"),
            }
        )
    return out


def create_event(
    uid: str,
    summary: str,
    description: str,
    start: datetime,
    minutes: int,
    tz_name: str,
    calendar_id: str = "primary",
) -> str:
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz_name},
        "end": {"dateTime": (start + timedelta(minutes=max(minutes, 5))).isoformat(), "timeZone": tz_name},
        "extendedProperties": {"private": {"cyoa": "1"}},
        "reminders": {"useDefault": True},
    }
    ev = _service(uid).events().insert(calendarId=calendar_id, body=body).execute()
    return ev["id"]


def delete_event(uid: str, event_id: str, calendar_id: str = "primary") -> None:
    try:
        _service(uid).events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status not in (404, 410):
            raise
