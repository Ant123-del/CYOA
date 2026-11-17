"""Day planning as a background job, so people can leave while the AI writes their day.

Flow:
  1. POST /api/ai/plan-day creates planJobs/{jobId} (status "queued") and returns at once.
  2. The page immediately calls POST /api/ai/plan-jobs/{id}/run, which does the work in that
     request (it keeps running even if the person navigates away inside the app).
  3. Safety net: the every-minute scheduler (`sweep_jobs`) runs any job that was never
     started, or that died mid-way (e.g. the tab was closed and the request was cut off).
  4. The page polls GET /api/ai/plan-jobs/{id}; each poll stamps lastSeenAt.
  5. When the job finishes, the user is emailed if they asked to be ("Email me and leave")
     or if nobody has polled recently (they closed the tab / left the page).

planJobs is server-only like everything else (Firestore rules deny all browser access), and
every read checks the job belongs to the caller.
"""

import html
import logging
from datetime import UTC, datetime, timedelta
from datetime import date as date_cls

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from . import ai, coverage, meals, memory
from . import google_calendar as gcal
from .auth import load_settings_by_uid
from .config import get_settings
from .firebase import db
from .models import DayPlan, PlanDayIn, UserSettings
from .notifications import send_email
from .routers.days import save_day
from .routers.goals import list_goal_dicts
from .routers.sleep import summary_for
from .sleep import ai_context
from .timeutil import now_iso, tz

log = logging.getLogger("cyoa.plan_jobs")

JOBS = "planJobs"
AWAY_AFTER = timedelta(seconds=25)  # no poll for this long = they left the page
UNSTARTED_AFTER = timedelta(seconds=30)  # queued this long = the page never started it
DIED_AFTER = timedelta(minutes=6)  # "running" longer than the API's 5-min timeout = it died
STUCK_AFTER = timedelta(minutes=15)  # give up and show an error


# ---------- shared planning helpers ----------


def sleep_context(uid: str, settings: UserSettings) -> dict:
    try:
        return ai_context(summary_for(uid, settings), settings.timezone)
    except Exception:
        log.exception("Sleep summary failed; planning without it")
        return {"tracked": False}


def open_goals(uid: str, goal_ids: list[str] | None) -> list[dict]:
    goals = [g for g in list_goal_dicts(uid) if g.get("status") != "done"]
    if goal_ids is not None:
        wanted = set(goal_ids)
        goals = [g for g in goals if g["id"] in wanted]
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(goals, key=lambda g: (rank.get(g.get("priority"), 1), g.get("dueDate") or "9999"))[:60]


def generate_day(uid: str, body: PlanDayIn) -> DayPlan:
    """Build, save and remember a branching plan for one day (raises ai.AIError)."""
    settings = load_settings_by_uid(uid) or UserSettings()
    weekday = date_cls.fromisoformat(body.date).strftime("%A")

    events: list[dict] = []
    if body.useCalendar:
        try:
            events = [e for e in gcal.list_events(uid, body.date, settings.timezone) if not e["createdByCyoa"]]
        except gcal.CalendarNotConnected:
            events = []
        except Exception:
            log.exception("Calendar fetch failed; planning without it")

    sleep_ctx = sleep_context(uid, settings)
    windows = meals.meal_windows(settings, body.dayStart, body.dayEnd, sleep_ctx.get("woke_at_local"), body.date)
    plan, learned = ai.plan_day(
        date=body.date,
        weekday=weekday,
        timezone=settings.timezone,
        priorities=body.priorities,
        day_start=body.dayStart,
        day_end=body.dayEnd,
        goals=open_goals(uid, body.goalIds),
        events=events,
        routes=body.routes,
        sleep=sleep_ctx,
        is_today=body.date == datetime.now(tz(settings.timezone)).date().isoformat(),
        memory=memory.context_for(uid, body.date),
        meals=windows,
        meal_notes=settings.mealNotes,
        timelines=body.timelines,
    )
    # Safety nets, per timeline: no calendar event is dropped, every meal is guaranteed.
    added: list[str] = []
    tracks = [(t.id, set(t.keptEventIds)) for t in plan.timelines] or [(None, None)]
    rebuilt = []
    for tid, kept in tracks:
        track = plan.model_copy(update={"chapters": [c for c in plan.chapters if c.timelineId == tid]})
        added += coverage.ensure_events(track, [e for e in events if kept is None or e["id"] in kept])
        added += meals.ensure_meals(track, windows)
        added += coverage.resolve_overlaps(track)  # nothing on one timeline overlaps
        for c in track.chapters:
            c.timelineId = tid
        rebuilt.extend(track.chapters)
    plan.chapters = rebuilt
    if added:
        log.info("Safety net for %s on %s: %s", uid, body.date, "; ".join(added))
    saved = save_day(uid, plan, settings)
    memory.record(
        uid,
        kind="plan_day",
        day=body.date,
        text=body.priorities or "(planned without stating priorities)",
        learned=learned.learned,
        outdated_ids=learned.outdated_note_ids,
    )
    return saved


# ---------- jobs ----------


def _ref(job_id: str):
    return db().collection(JOBS).document(job_id)


def _public(job_id: str, d: dict) -> dict:
    status = d["status"]
    started = d.get("startedAt") or d.get("createdAt")
    if status in ("queued", "running") and started and datetime.now(UTC) - started > STUCK_AFTER:
        status = "error"  # the worker died (e.g. timed out) - let the user retry
    return {
        "jobId": job_id,
        "date": d["date"],
        "status": status,
        "error": d.get("error") or ("Planning took too long - please try again." if status != d["status"] else None),
        "notifyEmail": bool(d.get("notifyEmail")),
        "createdAt": d["createdAt"].isoformat() if d.get("createdAt") else None,
    }


def active_job(uid: str, day: str) -> dict | None:
    """The newest unfinished job for this user + day, if any."""
    docs = db().collection(JOBS).where(filter=FieldFilter("uid", "==", uid)).where(filter=FieldFilter("date", "==", day)).stream()
    jobs = sorted(((d.id, d.to_dict()) for d in docs), key=lambda x: x[1]["createdAt"], reverse=True)
    for job_id, d in jobs:
        pub = _public(job_id, d)
        if pub["status"] in ("queued", "running"):
            return pub
    return None


def create_job(uid: str, body: PlanDayIn) -> dict:
    existing = active_job(uid, body.date)
    if existing:  # don't run two plans for the same day at once
        return existing
    now = datetime.now(UTC)
    ref = db().collection(JOBS).document()
    data = {
        "uid": uid,
        "date": body.date,
        "status": "queued",
        "request": body.model_dump(),
        "createdAt": now,
        "lastSeenAt": now,
        "notifyEmail": False,
    }
    ref.set(data)
    return _public(ref.id, data)


def start_job(uid: str, job_id: str) -> dict | None:
    """Run the caller's job now, inside this request (called right after create_job)."""
    snap = _ref(job_id).get()
    if not snap.exists or snap.to_dict().get("uid") != uid:
        return None
    run_job(job_id)
    return _public(job_id, _ref(job_id).get().to_dict())


def sweep_jobs() -> int:
    """Run jobs nobody started, or restart ones that died. Called every minute."""
    now = datetime.now(UTC)
    ran = 0
    for status, older_than, field in (("queued", UNSTARTED_AFTER, "createdAt"), ("running", DIED_AFTER, "startedAt")):
        docs = db().collection(JOBS).where(filter=FieldFilter("status", "==", status)).limit(20).stream()
        for d in docs:
            stamp = d.to_dict().get(field)
            if stamp and now - stamp > older_than and now - d.to_dict()["createdAt"] < STUCK_AFTER:
                log.info("Sweeper running %s job %s", status, d.id)
                run_job(d.id, allow_stale_running=status == "running")
                ran += 1
    return ran


def get_job(uid: str, job_id: str, *, seen: bool = True) -> dict | None:
    ref = _ref(job_id)
    snap = ref.get()
    if not snap.exists or snap.to_dict().get("uid") != uid:
        return None  # never reveal other people's jobs
    if seen:
        ref.update({"lastSeenAt": datetime.now(UTC)})
    return _public(job_id, snap.to_dict())


def request_email(uid: str, job_id: str) -> dict | None:
    ref = _ref(job_id)
    snap = ref.get()
    if not snap.exists or snap.to_dict().get("uid") != uid:
        return None
    d = snap.to_dict()
    if d["status"] in ("done", "error"):  # finished between click and request: send now
        ref.update({"notifyEmail": True})
        _notify(job_id, {**d, "notifyEmail": True}, force=True)
    else:
        ref.update({"notifyEmail": True})
    return _public(job_id, {**d, "notifyEmail": True})


def _claim(job_id: str, allow_stale_running: bool = False) -> dict | None:
    """queued -> running exactly once, so the page and the sweeper never both run a job.
    A job stuck in "running" past DIED_AFTER may be re-claimed by the sweeper."""
    ref = _ref(job_id)

    @firestore.transactional
    def txn(transaction):
        snap = ref.get(transaction=transaction)
        d = snap.to_dict() if snap.exists else None
        if not d:
            return None
        stale = (
            allow_stale_running
            and d.get("status") == "running"
            and datetime.now(UTC) - (d.get("startedAt") or d["createdAt"]) > DIED_AFTER
        )
        if d.get("status") != "queued" and not stale:
            return None
        transaction.update(ref, {"status": "running", "startedAt": datetime.now(UTC)})
        return snap.to_dict()

    return txn(db().transaction())


def run_job(job_id: str, allow_stale_running: bool = False) -> None:
    job = _claim(job_id, allow_stale_running)
    if not job:
        return
    uid = job["uid"]
    try:
        plan = generate_day(uid, PlanDayIn(**job["request"]))
        _ref(job_id).update({"status": "done", "finishedAt": datetime.now(UTC), "summary": plan.summary})
    except ai.AIError as exc:
        _ref(job_id).update({"status": "error", "finishedAt": datetime.now(UTC), "error": str(exc)})
    except Exception:
        log.exception("Plan job %s failed", job_id)
        _ref(job_id).update(
            {"status": "error", "finishedAt": datetime.now(UTC), "error": "Something went wrong while planning. Please try again."}
        )
    _notify(job_id, _ref(job_id).get().to_dict())


# ---------- email when ready ----------


def _notify(job_id: str, d: dict, force: bool = False) -> None:
    away = datetime.now(UTC) - (d.get("lastSeenAt") or d["createdAt"]) > AWAY_AFTER
    if d.get("emailedAt") or not (force or d.get("notifyEmail") or away):
        return
    settings = load_settings_by_uid(d["uid"])
    to = settings and (settings.notifyEmail or settings.email)
    if not to:
        return
    try:
        send_email(to, *_email(d, settings))
        _ref(job_id).update({"emailedAt": now_iso()})
    except Exception:
        log.exception("Plan-ready email failed for job %s", job_id)


def _email(d: dict, settings: UserSettings) -> tuple[str, str, str]:
    day = d["date"]
    pretty = date_cls.fromisoformat(day).strftime("%A, %b %-d")
    base = get_settings().app_url
    if d["status"] == "done":
        link = f"{base}/today?date={day}"
        summary = html.escape(d.get("summary") or "")
        subject = f"🗺️ Your adventure for {pretty} is ready"
        body = (
            f"<h2 style='margin-bottom:4px'>Your adventure for {pretty} is ready</h2>"
            f"<p style='color:#555'>{summary}</p>"
            f"<p><a href='{link}' style='background:#7c5cff;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none'>See your day</a></p>"
        )
        text = f"Your adventure for {pretty} is ready.\n\n{d.get('summary') or ''}\n\nSee it: {link}"
    else:
        link = f"{base}/plan?date={day}"
        reason = html.escape(d.get("error") or "Something went wrong.")
        subject = f"We couldn't finish planning {pretty}"
        body = (
            f"<h2 style='margin-bottom:4px'>We couldn't finish planning {pretty}</h2>"
            f"<p style='color:#555'>{reason}</p>"
            f"<p><a href='{link}' style='background:#7c5cff;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none'>Try again</a></p>"
        )
        text = f"We couldn't finish planning {pretty}: {d.get('error')}\n\nTry again: {link}"
    html_body = (
        "<div style='font-family:system-ui,sans-serif;max-width:560px;margin:auto'>"
        + body
        + "<p style='color:#999;font-size:12px'>CYOA — Choose Your Own Adventure</p></div>"
    )
    return subject, html_body, text
