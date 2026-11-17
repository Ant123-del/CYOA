"""Google Calendar access through calendar *sharing* (no per-user OAuth).

How a user links a calendar:
  1. In Google Calendar they share their calendar with CYOA's service account
     ("Make changes to events").
  2. They paste the calendar's Calendar ID into CYOA's Settings.

Security rules enforced here (the browser can never bypass them):
  1. Calendar IDs are validated: format + length, and "primary" / the service account's
     own calendar are refused.
  2. The service account must really have write access (checked when linking).
  3. The user must prove they own the calendar - otherwise anyone could paste someone
     else's Calendar ID:
       a. the ID equals their own verified Google sign-in email (their primary calendar), or
       b. they put a one-time code in the calendar's Description. Only people who manage
          the calendar can edit that; CYOA itself only has event access.
  4. The linked ID lives server-side in users/{uid}/private/calendar. The settings API
     cannot set it, and every calendar call uses only the caller's own linked calendar.
  5. CYOA only deletes events it created *for that same user* (tagged on creation).
  6. If the share is revoked, the link is removed automatically.
"""

import json
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import get_settings
from .firebase import user_ref
from .timeutil import day_bounds, tz

log = logging.getLogger("cyoa.calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID_RE = re.compile(r"^[A-Za-z0-9._%+\-#]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MAX_ID_LENGTH = 254
CHALLENGE_TTL = timedelta(hours=24)


class CalendarNotConnected(Exception):
    pass


class CalendarLinkError(Exception):
    """A user-facing reason the calendar could not be linked."""


# ---------- service account ----------


@lru_cache
def _credentials():
    key = get_settings().service_account_path
    if key.exists():  # local dev
        return service_account.Credentials.from_service_account_file(str(key), scopes=SCOPES)
    creds, _ = google.auth.default(scopes=SCOPES)  # Cloud Functions runtime identity
    return creds


def _service():
    # Built per call: the underlying HTTP client isn't thread-safe.
    return build("calendar", "v3", credentials=_credentials(), cache_discovery=False)


def service_account_email() -> str:
    s = get_settings()
    if s.calendar_service_account:
        return s.calendar_service_account
    key = s.service_account_path
    if key.exists():
        return json.loads(key.read_text()).get("client_email", "")
    return ""


# ---------- storage ----------


def _link_ref(uid: str):
    return user_ref(uid).collection("private").document("calendar")


def _challenge_ref(uid: str):
    return user_ref(uid).collection("private").document("calendarChallenge")


def linked_calendar_id(uid: str) -> str:
    snap = _link_ref(uid).get()
    if not snap.exists:
        raise CalendarNotConnected()
    return snap.to_dict()["calendarId"]


def is_connected(uid: str) -> bool:
    return _link_ref(uid).get().exists


def unlink(uid: str) -> None:
    _link_ref(uid).delete()
    _challenge_ref(uid).delete()
    user_ref(uid).set({"googleConnected": False, "calendarId": "", "calendarName": ""}, merge=True)


def _access_lost(uid: str, exc: HttpError) -> CalendarNotConnected:
    log.warning("Calendar access lost for %s (%s); unlinking", uid, exc.resp.status)
    unlink(uid)
    return CalendarNotConnected()


# ---------- linking ----------


def normalize_calendar_id(raw: str) -> str:
    """Accept a bare Calendar ID, or a pasted Google Calendar embed / public URL."""
    text = (raw or "").strip()
    if text.startswith("http"):
        qs = parse_qs(urlparse(text).query)
        text = (qs.get("src") or qs.get("cid") or [""])[0]
    cid = unquote(text).strip()
    if not cid or len(cid) > MAX_ID_LENGTH or not CALENDAR_ID_RE.match(cid):
        raise CalendarLinkError(
            "That doesn't look like a Calendar ID. It looks like an email address, e.g. "
            "you@gmail.com or abc123@group.calendar.google.com."
        )
    if cid.lower() == service_account_email().lower():
        raise CalendarLinkError("That's CYOA's own address - paste the ID of your calendar instead.")
    return cid


def _check_access(cid: str) -> dict:
    """Make sure the calendar is shared with the service account with write access."""
    svc = _service()
    share_hint = (
        f"CYOA can't edit that calendar yet. In Google Calendar open Settings → your calendar → "
        f"'Share with specific people', add {service_account_email()} with "
        f"'Make changes to events', then try again."
    )
    try:
        entry = svc.calendarList().insert(body={"id": cid}).execute()
    except HttpError as exc:
        if exc.resp.status == 403 and any(s in (exc.content or b"") for s in (b"SERVICE_DISABLED", b"accessNotConfigured")):
            log.error("Google Calendar API is disabled for this project")
            raise CalendarLinkError(
                "Calendar linking isn't switched on for CYOA yet (the Google Calendar API is disabled). Try again later."
            ) from exc
        if exc.resp.status == 409:  # already in the list
            entry = svc.calendarList().get(calendarId=cid).execute()
        elif exc.resp.status in (403, 404):
            raise CalendarLinkError(share_hint) from exc
        else:
            raise
    if entry.get("accessRole") not in ("writer", "owner"):
        raise CalendarLinkError(share_hint.replace("can't edit", "only has view access to"))
    return entry


def _save_link(uid: str, cid: str, name: str, method: str) -> dict:
    _link_ref(uid).set({"calendarId": cid, "calendarName": name, "method": method, "linkedAt": datetime.now(UTC)})
    _challenge_ref(uid).delete()
    user_ref(uid).set({"googleConnected": True, "calendarId": cid, "calendarName": name}, merge=True)
    return {"status": "linked", "calendarId": cid, "calendarName": name}


def link_calendar(uid: str, email: str, email_verified: bool, raw_id: str) -> dict:
    cid = normalize_calendar_id(raw_id)
    entry = _check_access(cid)
    name = entry.get("summaryOverride") or entry.get("summary") or cid

    # Rule 3a: your own primary calendar (its ID is your verified Google email).
    if email_verified and email and cid.lower() == email.lower():
        return _save_link(uid, cid, name, "verified_email")

    # Rule 3b: prove you manage the calendar with a one-time code in its description.
    now = datetime.now(UTC)
    snap = _challenge_ref(uid).get()
    ch = snap.to_dict() if snap.exists else None
    if ch and ch["calendarId"].lower() == cid.lower() and ch["expiresAt"] > now:
        description = _service().calendars().get(calendarId=cid).execute().get("description") or ""
        if ch["code"] in description:
            return _save_link(uid, cid, name, "description_code")
        return {
            "status": "verify",
            "calendarId": cid,
            "calendarName": name,
            "code": ch["code"],
            "message": "The code isn't in the calendar's description yet (changes can take a minute).",
        }

    code = "CYOA-" + secrets.token_hex(4).upper()
    _challenge_ref(uid).set({"calendarId": cid, "code": code, "expiresAt": now + CHALLENGE_TTL})
    return {"status": "verify", "calendarId": cid, "calendarName": name, "code": code, "message": ""}


def info(uid: str) -> dict:
    link = _link_ref(uid).get()
    ch = _challenge_ref(uid).get()
    pending = None
    if ch.exists and ch.to_dict()["expiresAt"] > datetime.now(UTC):
        pending = {"calendarId": ch.to_dict()["calendarId"], "code": ch.to_dict()["code"]}
    data = link.to_dict() if link.exists else {}
    return {
        "serviceAccountEmail": service_account_email(),
        "linked": link.exists,
        "calendarId": data.get("calendarId", ""),
        "calendarName": data.get("calendarName", ""),
        "pending": pending,
    }


# ---------- events (always the caller's own linked calendar) ----------


def list_events(uid: str, day: str, tz_name: str) -> list[dict]:
    cid = linked_calendar_id(uid)
    start, end = day_bounds(day, tz_name)
    try:
        resp = (
            _service()
            .events()
            .list(
                calendarId=cid,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=100,
            )
            .execute()
        )
    except HttpError as exc:
        if exc.resp.status in (403, 404):
            raise _access_lost(uid, exc) from exc
        raise
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
            start_hm = datetime.fromisoformat(s["dateTime"]).astimezone(zone).strftime("%H:%M")
            end_hm = datetime.fromisoformat(e["dateTime"]).astimezone(zone).strftime("%H:%M")
        out.append(
            {
                "id": ev["id"],
                "summary": ev.get("summary", "(no title)"),
                "description": (ev.get("description") or "")[:500],
                "start": start_hm,
                "end": end_hm,
                "allDay": all_day,
                "createdByCyoa": ev.get("extendedProperties", {}).get("private", {}).get("cyoa") == "1",
            }
        )
    return out


def create_event(uid: str, summary: str, description: str, start: datetime, minutes: int, tz_name: str) -> str:
    cid = linked_calendar_id(uid)
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz_name},
        "end": {"dateTime": (start + timedelta(minutes=max(minutes, 5))).isoformat(), "timeZone": tz_name},
        # Tag so CYOA can recognise (and only ever delete) its own events for this user.
        "extendedProperties": {"private": {"cyoa": "1", "cyoaUid": uid}},
        "reminders": {"useDefault": True},
    }
    try:
        return _service().events().insert(calendarId=cid, body=body).execute()["id"]
    except HttpError as exc:
        if exc.resp.status in (403, 404):
            raise _access_lost(uid, exc) from exc
        raise


def delete_event(uid: str, event_id: str) -> None:
    """Delete an event only if CYOA created it for this user (rule 5)."""
    cid = linked_calendar_id(uid)
    svc = _service()
    try:
        ev = svc.events().get(calendarId=cid, eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status in (404, 410):
            return
        raise
    props = ev.get("extendedProperties", {}).get("private", {})
    if props.get("cyoa") != "1" or props.get("cyoaUid") != uid:
        log.warning("Refusing to delete event %s for %s: not created by CYOA for this user", event_id, uid)
        return
    try:
        svc.events().delete(calendarId=cid, eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status not in (404, 410):
            raise
