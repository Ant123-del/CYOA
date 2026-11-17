import logging
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException

from .. import ai
from .. import google_calendar as gcal
from ..auth import CurrentUser, current_user, get_user_settings
from ..models import ChapterOptionsIn, DayPlan, PlanDayIn
from .days import load_day, save_day
from .goals import list_goal_dicts

log = logging.getLogger("cyoa.ai.router")
router = APIRouter(prefix="/api/ai", tags=["ai"])


def _open_goals(uid: str, goal_ids: list[str] | None) -> list[dict]:
    goals = [g for g in list_goal_dicts(uid) if g.get("status") != "done"]
    if goal_ids is not None:
        wanted = set(goal_ids)
        goals = [g for g in goals if g["id"] in wanted]
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(goals, key=lambda g: (rank.get(g.get("priority"), 1), g.get("dueDate") or "9999"))[:60]


@router.post("/plan-day", response_model=DayPlan)
def plan_day(body: PlanDayIn, user: CurrentUser = Depends(current_user)):
    """Generate (and save) a branching plan for a day from goals + priorities + calendar."""
    settings = get_user_settings(user)
    try:
        weekday = date_cls.fromisoformat(body.date).strftime("%A")
    except ValueError as exc:
        raise HTTPException(400, "Date must be YYYY-MM-DD") from exc

    events: list[dict] = []
    if body.useCalendar:
        try:
            events = [e for e in gcal.list_events(user.uid, body.date, settings.timezone, settings.calendarId) if not e["createdByCyoa"]]
        except gcal.CalendarNotConnected:
            events = []
        except Exception:
            log.exception("Calendar fetch failed; planning without it")

    try:
        plan = ai.plan_day(
            date=body.date,
            weekday=weekday,
            timezone=settings.timezone,
            priorities=body.priorities,
            day_start=body.dayStart,
            day_end=body.dayEnd,
            goals=_open_goals(user.uid, body.goalIds),
            events=events,
            routes=body.routes,
        )
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    return save_day(user.uid, plan, settings)


@router.post("/chapter-options", response_model=DayPlan)
def chapter_options(body: ChapterOptionsIn, user: CurrentUser = Depends(current_user)):
    """Ask the AI for a fresh set of options for one chapter."""
    settings = get_user_settings(user)
    plan = load_day(user.uid, body.date)
    if not plan:
        raise HTTPException(404, "No plan for this day")
    ch = next((c for c in plan.chapters if c.id == body.chapterId), None)
    if not ch:
        raise HTTPException(404, "Chapter not found")
    try:
        ch.options = ai.regenerate_options(day=plan, chapter=ch, goals=_open_goals(user.uid, None), hint=body.hint)
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    ch.chosenOptionId = None
    return save_day(user.uid, plan, settings)
