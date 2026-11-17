import logging
from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter
from googleapiclient.errors import HttpError

from .. import google_calendar as gcal
from ..auth import CurrentUser, current_user, get_user_settings
from ..firebase import user_ref
from ..models import Chapter, ChooseIn, DayPlan, Option
from ..notifications import clear_reminder, rebuild_reminders
from ..timeutil import local_dt, minutes_between, new_id, now_iso, tz

log = logging.getLogger("cyoa.days")
router = APIRouter(prefix="/api/days", tags=["days"])


def _validate_date(day: str) -> str:
    try:
        date_cls.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(400, "Date must be YYYY-MM-DD") from exc
    return day


def _ref(uid: str, day: str):
    return user_ref(uid).collection("days").document(_validate_date(day))


def load_day(uid: str, day: str) -> DayPlan | None:
    snap = _ref(uid, day).get()
    return DayPlan(**snap.to_dict()) if snap.exists else None


def save_day(uid: str, plan: DayPlan, settings) -> DayPlan:
    plan.chapters.sort(key=lambda c: c.start)
    plan.updatedAt = now_iso()
    _ref(uid, plan.date).set(plan.model_dump())
    rebuild_reminders(uid, plan, settings)
    return plan


@router.get("")
def list_days(start: str, end: str, user: CurrentUser = Depends(current_user)):
    """Lightweight summaries for a date range (inclusive), e.g. the week strip."""
    out = []
    for snap in user_ref(user.uid).collection("days").where(filter=FieldFilter("date", ">=", start)).where(filter=FieldFilter("date", "<=", end)).stream():
        d = snap.to_dict()
        chapters = d.get("chapters", [])
        out.append(
            {
                "date": d["date"],
                "chapters": len(chapters),
                "chosen": sum(1 for c in chapters if c.get("chosenOptionId")),
                "storylines": len(d.get("storylines", [])),
            }
        )
    return sorted(out, key=lambda x: x["date"])


@router.get("/{day}", response_model=DayPlan | None)
def get_day(day: str, user: CurrentUser = Depends(current_user)):
    return load_day(user.uid, day)


@router.put("/{day}", response_model=DayPlan)
def put_day(day: str, plan: DayPlan, user: CurrentUser = Depends(current_user)):
    if plan.date != day:
        raise HTTPException(400, "Body date does not match URL")
    return save_day(user.uid, plan, get_user_settings(user))


@router.delete("/{day}")
def delete_day(day: str, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    _ref(user.uid, day).delete()
    rebuild_reminders(user.uid, DayPlan(date=day), settings)
    return {"ok": True}


def calendar_chapter(ev: dict) -> Chapter:
    """Template chapter for an existing calendar event: yes / yes-and / no / no-and."""
    mins = minutes_between(ev["start"], ev["end"])
    name = ev["summary"]
    return Chapter(
        id=new_id(),
        start=ev["start"],
        end=ev["end"],
        title=name,
        source="calendar",
        calendarEventId=ev["id"],
        options=[
            Option(id=new_id(), kind="yes", title=f"Go: {name}", detail="Stick with the plan.", durationMinutes=mins),
            Option(id=new_id(), kind="yes_and", title=f"{name} + follow-up", detail="Do it, then capture notes / next steps.", durationMinutes=30),
            Option(id=new_id(), kind="no", title="Skip it, do something else", detail="Swap in a same-priority task.", durationMinutes=mins),
            Option(id=new_id(), kind="no_and", title="Skip it, and recover the value", detail="Do an alternative and catch up asynchronously.", durationMinutes=mins),
        ],
    )


@router.post("/{day}/import-calendar", response_model=list[Chapter])
def import_calendar(day: str, user: CurrentUser = Depends(current_user)):
    """Turn the day's Google Calendar events into yes/yes-and/no/no-and chapters (not saved)."""
    settings = get_user_settings(user)
    try:
        events = gcal.list_events(user.uid, _validate_date(day), settings.timezone)
    except gcal.CalendarNotConnected as exc:
        raise HTTPException(409, "No Google Calendar linked") from exc
    return [calendar_chapter(e) for e in events if not e["allDay"] and not e["createdByCyoa"]]


def _find(plan: DayPlan, chapter_id: str) -> Chapter:
    ch = next((c for c in plan.chapters if c.id == chapter_id), None)
    if not ch:
        raise HTTPException(404, "Chapter not found")
    return ch


@router.post("/{day}/chapters/{chapter_id}/choose")
def choose(day: str, chapter_id: str, body: ChooseIn, user: CurrentUser = Depends(current_user)):
    """Pick a path for a chapter and put it on the user's Google Calendar."""
    settings = get_user_settings(user)
    plan = load_day(user.uid, day)
    if not plan:
        raise HTTPException(404, "No plan for this day")
    ch = _find(plan, chapter_id)
    opt = next((o for o in ch.options if o.id == body.optionId), None)
    if not opt:
        raise HTTPException(404, "Option not found")

    calendar_status = "skipped"
    # Changing your mind: remove the event we created for the previous choice.
    if ch.scheduledEventId:
        try:
            gcal.delete_event(user.uid, ch.scheduledEventId)
        except Exception:
            log.exception("Could not delete previous event")
        ch.scheduledEventId = None

    wants_event = body.addToCalendar and not (ch.source == "calendar" and opt.kind == "yes")
    if ch.source == "calendar" and opt.kind == "yes":
        calendar_status = "existing"  # it's already on the calendar
    if wants_event:
        chapter_start = local_dt(day, ch.start, settings.timezone)
        if ch.source == "calendar" and opt.kind == "yes_and":
            start = local_dt(day, ch.end, settings.timezone)  # the "and" comes after the event
        else:
            now = datetime.now(tz(settings.timezone))
            rounded = (now + timedelta(minutes=4)).replace(second=0, microsecond=0)
            rounded -= timedelta(minutes=rounded.minute % 5)
            start = max(chapter_start, rounded) if now.date().isoformat() == day else chapter_start
        minutes = opt.durationMinutes or minutes_between(ch.start, ch.end)
        storyline = next((s.name for s in plan.storylines if s.id == opt.storylineId), "")
        description = "\n".join(
            filter(None, [opt.detail, f"Chapter: {ch.title}", f"Storyline: {storyline}" if storyline else "", "— chosen in CYOA"])
        )
        try:
            ch.scheduledEventId = gcal.create_event(
                user.uid, f"🧭 {opt.title}", description, start, minutes, settings.timezone
            )
            calendar_status = "created"
        except gcal.CalendarNotConnected:
            calendar_status = "not_connected"
        except HttpError as exc:
            log.exception("Calendar insert failed")
            calendar_status = f"error: {exc.resp.status}"

    ch.chosenOptionId = opt.id
    ch.chosenAt = now_iso()
    save_day(user.uid, plan, settings)
    clear_reminder(user.uid, day, ch.id)
    return {"plan": plan, "calendar": calendar_status}


@router.post("/{day}/chapters/{chapter_id}/reset", response_model=DayPlan)
def reset_choice(day: str, chapter_id: str, user: CurrentUser = Depends(current_user)):
    """Undo a choice (removes the event CYOA created) so a different path can be taken."""
    settings = get_user_settings(user)
    plan = load_day(user.uid, day)
    if not plan:
        raise HTTPException(404, "No plan for this day")
    ch = _find(plan, chapter_id)
    if ch.scheduledEventId:
        try:
            gcal.delete_event(user.uid, ch.scheduledEventId)
        except Exception:
            log.exception("Could not delete event")
    ch.chosenOptionId = ch.chosenAt = ch.scheduledEventId = None
    return save_day(user.uid, plan, settings)
