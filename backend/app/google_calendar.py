"""Google Calendar access through calendar *sharing* (no per-user OAuth), multiple calendars per user.

How a user links a calendar:
  1. In Google Calendar they share the calendar with CYOA's service account
     ("Make changes to events").
  2. They paste the calendar's Calendar ID into CYOA's Settings. Repeat for each calendar
     (work, personal, family...), up to MAX_CALENDARS.

Calendars can be shared two ways:
  - "Make changes to events"   -> canWrite: CYOA may add chosen paths there.
  - "See all event details"    -> view-only: CYOA only reads it for planning.
Only one editable calendar is needed (the default); any number can be view-only.

Each linked calendar has these switches:
  - readEnabled: its events are pulled into planning / the "import calendar" button.
  - readOnly:    the user's "never edit this calendar" choice, even if CYOA could.
  - isDefault:   where CYOA writes chosen paths. Exactly one *writable* calendar
                 (canWrite and not readOnly) is the default; none if nothing is writable.
                 Paths chosen for a chapter that came from an event on a writable calendar
                 go back to that calendar; everything else goes to the default.

Security rules enforced here (the browser can never bypass them):
  1. Calendar IDs are validated: format + length, and "primary" / the service account's
     own calendar are refused.
  2. The service account must really have write access (checked when linking).
  3. The user must prove they own each calendar - otherwise anyone could paste someone
     else's Calendar ID:
       a. the ID equals their own verified Google sign-in email (their primary calendar), or
       b. they put a one-time code in the calendar's Description. Only people who manage
          the calendar can edit that; CYOA itself only has event access.
  4. Linked calendars live server-side in users/{uid}/calendars (Firestore rules deny all
     browser access). Any calendar ID that arrives from the browser - e.g. inside a saved
     day plan - is only used if it is one of *this user's* linked calendars.
  5. CYOA only deletes events it created *for that same user* (tagged on creation), and
     never writes to or deletes from a view-only / "never edit" calendar.
  6. If a share is revoked, that calendar is unlinked automatically.
"""

import hashlib
import json
import logging
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import get_settings
from .firebase import db, user_ref
from .timeutil import day_bounds, tz

log = logging.getLogger("cyoa.calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID_RE = re.compile(r"^[A-Za-z0-9._%+\-#]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MAX_ID_LENGTH = 254
MAX_CALENDARS = 10
CHALLENGE_TTL = timedelta(hours=24)


class CalendarNotConnected(Exception):
    pass


class NoWritableCalendar(CalendarNotConnected):
    """Calendars are linked, but none of them may be edited."""


class CalendarLinkError(Exception):
    """A user-facing reason the calendar could not be linked."""


def is_writable(c: dict) -> bool:
    # Calendars linked before view-only support were all verified as writable.
    return bool(c.get("canWrite", True)) and not c.get("readOnly", False)


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


def calendar_key(calendar_id: str) -> str:
    """Stable Firestore-safe document id for a calendar ID."""
    return hashlib.sha256(calendar_id.strip().lower().encode()).hexdigest()[:16]


def _cals_col(uid: str):
    return user_ref(uid).collection("calendars")


def _legacy_ref(uid: str):  # single-calendar storage from the first version
    return user_ref(uid).collection("private").document("calendar")


def _challenge_ref(uid: str):
    return user_ref(uid).collection("private").document("calendarChallenge")


def _migrate_legacy(uid: str) -> None:
    snap = _legacy_ref(uid).get()
    if not snap.exists:
        return
    d = snap.to_dict()
    _cals_col(uid).document(calendar_key(d["calendarId"])).set(
        {
            "calendarId": d["calendarId"],
            "calendarName": d.get("calendarName") or d["calendarId"],
            "color": None,
            "method": d.get("method", "legacy"),
            "linkedAt": d.get("linkedAt") or datetime.now(UTC),
            "isDefault": True,
            "readEnabled": True,
            "canWrite": True,
            "readOnly": False,
        }
    )
    _legacy_ref(uid).delete()


def linked_calendars(uid: str) -> list[dict]:
    """This user's linked calendars (default first). Each dict includes its `key`."""
    cals = [{**d.to_dict(), "key": d.id} for d in _cals_col(uid).stream()]
    if not cals and _legacy_ref(uid).get().exists:
        _migrate_legacy(uid)
        cals = [{**d.to_dict(), "key": d.id} for d in _cals_col(uid).stream()]
    # Self-heal: exactly one default, and it must be writable (none if nothing is writable).
    for c in cals:
        if c.get("isDefault") and not is_writable(c):
            c["isDefault"] = False
            _cals_col(uid).document(c["key"]).update({"isDefault": False})
    defaults = [c for c in cals if c.get("isDefault")]
    for extra in defaults[1:]:
        extra["isDefault"] = False
        _cals_col(uid).document(extra["key"]).update({"isDefault": False})
    writable = sorted((c for c in cals if is_writable(c)), key=lambda c: str(c.get("linkedAt") or ""))
    if writable and not defaults:
        writable[0]["isDefault"] = True
        _cals_col(uid).document(writable[0]["key"]).update({"isDefault": True})
    return sorted(cals, key=lambda c: (not c.get("isDefault"), str(c.get("linkedAt") or "")))


def find_calendar(uid: str, calendar_id_or_key: str | None) -> dict | None:
    """Rule 4: only resolves calendars this user has linked."""
    if not calendar_id_or_key:
        return None
    needle = calendar_id_or_key.strip().lower()
    for c in linked_calendars(uid):
        if c["key"] == needle or c["calendarId"].lower() == needle:
            return c
    return None


def default_calendar(uid: str) -> dict:
    """The calendar CYOA writes to. Raises NoWritableCalendar if every link is view-only."""
    cals = linked_calendars(uid)
    if not cals:
        raise CalendarNotConnected()
    if not cals[0].get("isDefault"):
        raise NoWritableCalendar()
    return cals[0]


def is_connected(uid: str) -> bool:
    return bool(linked_calendars(uid))


def _sync_user_doc(uid: str) -> None:
    cals = linked_calendars(uid)
    default = cals[0] if cals and cals[0].get("isDefault") else None
    user_ref(uid).set(
        {
            "googleConnected": bool(cals),
            "calendarCount": len(cals),
            "hasWritableCalendar": default is not None,
            "calendarId": default["calendarId"] if default else "",
            "calendarName": default["calendarName"] if default else "",
        },
        merge=True,
    )


def unlink_calendar(uid: str, key: str) -> None:
    _cals_col(uid).document(key).delete()
    linked_calendars(uid)  # re-elects a default if needed
    _sync_user_doc(uid)


def unlink_all(uid: str) -> None:
    for c in linked_calendars(uid):
        _cals_col(uid).document(c["key"]).delete()
    _legacy_ref(uid).delete()
    _challenge_ref(uid).delete()
    _sync_user_doc(uid)


def update_calendar(
    uid: str,
    key: str,
    *,
    is_default: bool | None = None,
    read_enabled: bool | None = None,
    read_only: bool | None = None,
) -> None:
    cals = {c["key"]: c for c in linked_calendars(uid)}
    if key not in cals:
        raise CalendarNotConnected()
    cal = cals[key]
    if read_only is False and not cal.get("canWrite", True):
        raise CalendarLinkError(
            "This calendar is shared with CYOA as view-only. To let CYOA add events, change the share to "
            "'Make changes to events' in Google Calendar, then re-link it."
        )
    will_be_writable = cal.get("canWrite", True) and not (read_only if read_only is not None else cal.get("readOnly", False))
    if is_default and not will_be_writable:
        raise CalendarLinkError("Only a calendar CYOA is allowed to edit can be the default.")
    batch = db().batch()
    if is_default:
        for k in cals:
            batch.update(_cals_col(uid).document(k), {"isDefault": k == key})
    if read_enabled is not None:
        batch.update(_cals_col(uid).document(key), {"readEnabled": read_enabled})
    if read_only is not None:
        batch.update(_cals_col(uid).document(key), {"readOnly": read_only, **({"isDefault": False} if read_only else {})})
    batch.commit()
    linked_calendars(uid)  # re-elect a writable default if needed
    _sync_user_doc(uid)


def _access_lost(uid: str, cal: dict, exc: HttpError) -> None:
    log.warning("Calendar access lost for %s on %s (%s); unlinking it", uid, cal["calendarId"], exc.resp.status)
    unlink_calendar(uid, cal["key"])


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
    """Make sure the calendar is shared with the service account with at least
    "See all event details". Write access is recorded but optional."""
    svc = _service()
    share_hint = (
        f"CYOA can't see that calendar yet. In Google Calendar open Settings → your calendar → "
        f"'Share with specific people', add {service_account_email()} with 'Make changes to events' "
        f"(or 'See all event details' if CYOA should only read it), then try again."
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
    if entry.get("accessRole") not in ("writer", "owner", "reader"):
        raise CalendarLinkError(
            "That calendar is shared as free/busy only, so CYOA can't see your events. Change the share to "
            "'See all event details' (view-only) or 'Make changes to events', then try again."
        )
    return entry


def _public(c: dict) -> dict:
    return {
        "key": c["key"],
        "calendarId": c["calendarId"],
        "calendarName": c.get("calendarName") or c["calendarId"],
        "color": c.get("color"),
        "isDefault": bool(c.get("isDefault")),
        "readEnabled": c.get("readEnabled", True),
        "canWrite": bool(c.get("canWrite", True)),
        "readOnly": bool(c.get("readOnly", False)),
        "writable": is_writable(c),
    }


def _save_link(uid: str, cid: str, name: str, color: str | None, can_write: bool, method: str) -> dict:
    key = calendar_key(cid)
    ref = _cals_col(uid).document(key)
    existing = ref.get()
    data = {"calendarId": cid, "calendarName": name, "color": color, "method": method, "canWrite": can_write}
    if existing.exists:
        ref.update(data)  # re-linking refreshes access (e.g. a view-only share upgraded to edit)
    else:
        ref.set({**data, "linkedAt": datetime.now(UTC), "isDefault": False, "readEnabled": True, "readOnly": False})
    _challenge_ref(uid).delete()
    linked_calendars(uid)  # elects a writable default if there isn't one
    _sync_user_doc(uid)
    return {"status": "linked", **_public({**ref.get().to_dict(), "key": key})}


def link_calendar(uid: str, email: str, email_verified: bool, raw_id: str) -> dict:
    cid = normalize_calendar_id(raw_id)
    already = find_calendar(uid, cid)
    if not already and len(linked_calendars(uid)) >= MAX_CALENDARS:
        raise CalendarLinkError(f"You can link up to {MAX_CALENDARS} calendars. Remove one first.")
    entry = _check_access(cid)
    name = entry.get("summaryOverride") or entry.get("summary") or cid
    color = entry.get("backgroundColor")
    can_write = entry.get("accessRole") in ("writer", "owner")

    # Already proven for this user: just refresh name/colour.
    if already:
        return _save_link(uid, cid, name, color, can_write, already.get("method", "relink"))

    # Rule 3a: your own primary calendar (its ID is your verified Google email).
    if email_verified and email and cid.lower() == email.lower():
        return _save_link(uid, cid, name, color, can_write, "verified_email")

    # Rule 3b: prove you manage the calendar with a one-time code in its description.
    now = datetime.now(UTC)
    snap = _challenge_ref(uid).get()
    ch = snap.to_dict() if snap.exists else None
    if ch and ch["calendarId"].lower() == cid.lower() and ch["expiresAt"] > now:
        description = _service().calendars().get(calendarId=cid).execute().get("description") or ""
        if ch["code"] in description:
            return _save_link(uid, cid, name, color, can_write, "description_code")
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
    ch = _challenge_ref(uid).get()
    pending = None
    if ch.exists and ch.to_dict()["expiresAt"] > datetime.now(UTC):
        pending = {"calendarId": ch.to_dict()["calendarId"], "code": ch.to_dict()["code"]}
    return {
        "serviceAccountEmail": service_account_email(),
        "calendars": (cals := [_public(c) for c in linked_calendars(uid)]),
        "hasWritable": any(c["writable"] for c in cals),
        "maxCalendars": MAX_CALENDARS,
        "pending": pending,
    }


# ---------- events ----------


def _fetch_events(cal: dict, start: datetime, end: datetime) -> list[dict]:
    resp = (
        _service()
        .events()
        .list(
            calendarId=cal["calendarId"],
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )
    return resp.get("items", [])


def list_events(uid: str, day: str, tz_name: str) -> list[dict]:
    """Events for `day` from every linked calendar that's enabled for planning.

    Each event's `id` is "<calendarKey>:<eventId>" so events from different calendars
    never collide; `calendarId` / `calendarName` / `color` say where it came from.
    """
    cals = linked_calendars(uid)
    if not cals:
        raise CalendarNotConnected()
    cals = [c for c in cals if c.get("readEnabled", True)]
    start, end = day_bounds(day, tz_name)
    zone = tz(tz_name)

    def fetch(cal):
        try:
            return cal, _fetch_events(cal, start, end), None
        except HttpError as exc:
            return cal, [], exc

    out = []
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(cals)))) as pool:
        results = list(pool.map(fetch, cals))
    for cal, items, exc in results:
        if exc is not None:
            if exc.resp.status in (403, 404):
                _access_lost(uid, cal, exc)
            else:
                log.warning("Could not read %s: %s", cal["calendarId"], exc)
            continue
        for ev in items:
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
                    "id": f"{cal['key']}:{ev['id']}",
                    "eventId": ev["id"],
                    "calendarId": cal["calendarId"],
                    "calendarName": cal.get("calendarName") or cal["calendarId"],
                    "color": cal.get("color"),
                    "summary": ev.get("summary", "(no title)"),
                    "description": (ev.get("description") or "")[:500],
                    "start": start_hm,
                    "end": end_hm,
                    "allDay": all_day,
                    "createdByCyoa": ev.get("extendedProperties", {}).get("private", {}).get("cyoa") == "1",
                }
            )
    return sorted(out, key=lambda x: (x["start"], x["calendarName"]))


def create_event(
    uid: str,
    summary: str,
    description: str,
    start: datetime,
    minutes: int,
    tz_name: str,
    calendar_id: str | None = None,
) -> tuple[str, str]:
    """Create an event on `calendar_id` if it's one of the user's *writable* calendars, else
    on their default calendar. Returns (eventId, calendarId).
    Raises NoWritableCalendar if every linked calendar is view-only."""
    requested = find_calendar(uid, calendar_id)
    cal = requested if requested and is_writable(requested) else default_calendar(uid)
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
        ev = _service().events().insert(calendarId=cal["calendarId"], body=body).execute()
    except HttpError as exc:
        if exc.resp.status == 403:
            # The share was downgraded to view-only: remember that, then try the default.
            log.warning("Lost write access to %s for %s", cal["calendarId"], uid)
            _cals_col(uid).document(cal["key"]).update({"canWrite": False, "isDefault": False})
            linked_calendars(uid)
            _sync_user_doc(uid)
            fallback = default_calendar(uid)
            ev = _service().events().insert(calendarId=fallback["calendarId"], body=body).execute()
            return ev["id"], fallback["calendarId"]
        if exc.resp.status == 404:
            _access_lost(uid, cal, exc)
            raise CalendarNotConnected() from exc
        raise
    return ev["id"], cal["calendarId"]


def delete_event(uid: str, event_id: str, calendar_id: str | None = None) -> None:
    """Delete an event only if it's on one of this user's calendars and CYOA created it
    for this user (rules 4 + 5)."""
    cal = find_calendar(uid, calendar_id) if calendar_id else None
    if calendar_id and not cal:
        log.warning("Not deleting %s: calendar %s isn't linked for %s", event_id, calendar_id, uid)
        return
    try:
        cal = cal or default_calendar(uid)  # events from before multi-calendar support
    except CalendarNotConnected:
        return
    if not is_writable(cal):
        log.info("Not deleting %s: %s is view-only / never-edit", event_id, cal["calendarId"])
        return
    svc = _service()
    try:
        ev = svc.events().get(calendarId=cal["calendarId"], eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status in (404, 410):
            return
        raise
    props = ev.get("extendedProperties", {}).get("private", {})
    if props.get("cyoa") != "1" or props.get("cyoaUid") != uid:
        log.warning("Refusing to delete event %s for %s: not created by CYOA for this user", event_id, uid)
        return
    try:
        svc.events().delete(calendarId=cal["calendarId"], eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status not in (404, 410):
            raise
