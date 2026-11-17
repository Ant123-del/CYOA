from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user, get_user_settings
from ..models import SleepAt, SleepLogIn, SleepSession, SleepSummary, UserSettings
from ..sleep import MAX_SESSION_HOURS, parse_iso, recent_sessions, sleep_col, sleep_summary, to_iso
from ..timeutil import new_id, tz
from .days import load_day

router = APIRouter(prefix="/api/sleep", tags=["sleep"])

FUTURE_SLACK = timedelta(minutes=2)


def summary_for(uid: str, settings: UserSettings) -> SleepSummary:
    """Sleep summary, anchoring the bedtime suggestion to the next planned day's start if there is one."""
    local_now = datetime.now(UTC).astimezone(tz(settings.timezone))
    # Before 5am, the next wake-up is later today; otherwise it's tomorrow.
    wake_day = local_now.date() if local_now.hour < 5 else local_now.date() + timedelta(days=1)
    plan = load_day(uid, wake_day.isoformat())
    return sleep_summary(
        recent_sessions(uid),
        tz_name=settings.timezone,
        target_hours=settings.sleepTargetHours,
        tomorrow_wake=plan.dayStart if plan else None,
    )


def _when(at: str | None, field: str = "at") -> datetime:
    if not at:
        return datetime.now(UTC)
    try:
        dt = parse_iso(at)
    except ValueError as exc:
        raise HTTPException(400, f"{field} must be an ISO date-time") from exc
    if dt > datetime.now(UTC) + FUTURE_SLACK:
        raise HTTPException(400, "That time is in the future.")
    return dt


def _open_session(uid: str) -> SleepSession | None:
    return next((s for s in reversed(recent_sessions(uid)) if not s.end), None)


@router.get("", response_model=SleepSummary)
def get_sleep(user: CurrentUser = Depends(current_user)):
    return summary_for(user.uid, get_user_settings(user))


@router.post("/start", response_model=SleepSummary)
def start_sleep(body: SleepAt, user: CurrentUser = Depends(current_user)):
    """'Going to sleep' - opens a session (optionally backdated)."""
    settings = get_user_settings(user)
    if not _open_session(user.uid):
        sid = new_id()
        sleep_col(user.uid).document(sid).set(
            SleepSession(id=sid, start=to_iso(_when(body.at)), source="live").model_dump()
        )
    return summary_for(user.uid, settings)


@router.post("/cancel", response_model=SleepSummary)
def cancel_sleep(user: CurrentUser = Depends(current_user)):
    """Didn't actually go to sleep: drop the open session."""
    settings = get_user_settings(user)
    if s := _open_session(user.uid):
        sleep_col(user.uid).document(s.id).delete()
    return summary_for(user.uid, settings)


@router.post("/wake", response_model=SleepSummary)
def wake(body: SleepAt, user: CurrentUser = Depends(current_user)):
    """'Woke up' - closes the open session, now or at a given time."""
    settings = get_user_settings(user)
    s = _open_session(user.uid)
    if not s:
        raise HTTPException(409, "You're not marked as asleep.")
    end = _when(body.at)
    start = parse_iso(s.start)
    if end <= start:
        raise HTTPException(400, "Wake-up time must be after you went to sleep.")
    if end - start > timedelta(hours=MAX_SESSION_HOURS):
        raise HTTPException(400, f"That's over {MAX_SESSION_HOURS} hours of sleep - pick a later wake-up time, or cancel and log it manually.")
    sleep_col(user.uid).document(s.id).update({"end": to_iso(end)})
    return summary_for(user.uid, settings)


@router.post("/log", response_model=SleepSummary)
def log_sleep(body: SleepLogIn, user: CurrentUser = Depends(current_user)):
    """Add a sleep you forgot to track."""
    settings = get_user_settings(user)
    start, end = _when(body.start, "start"), _when(body.end, "end")
    if end <= start:
        raise HTTPException(400, "Wake-up time must be after you went to sleep.")
    if end - start > timedelta(hours=MAX_SESSION_HOURS):
        raise HTTPException(400, f"Sessions can be at most {MAX_SESSION_HOURS} hours.")
    for s in recent_sessions(user.uid):
        s_end = parse_iso(s.end) if s.end else datetime.now(UTC)
        if start < s_end and parse_iso(s.start) < end:
            raise HTTPException(409, "That overlaps a sleep you've already logged.")
    sid = new_id()
    sleep_col(user.uid).document(sid).set(
        SleepSession(id=sid, start=to_iso(start), end=to_iso(end), source="manual").model_dump()
    )
    return summary_for(user.uid, settings)


@router.delete("/{session_id}", response_model=SleepSummary)
def delete_sleep(session_id: str, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    sleep_col(user.uid).document(session_id).delete()
    return summary_for(user.uid, settings)
