import logging
from datetime import date as date_cls
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from .. import ai, meals, memory
from .. import google_calendar as gcal
from ..auth import CurrentUser, current_user, get_user_settings
from ..models import AIMemory, ChapterOptionsIn, DayPlan, MemoryNoteIn, PlanDayIn, UserSettings
from ..sleep import ai_context
from ..timeutil import tz
from .days import load_day, save_day
from .goals import list_goal_dicts
from .sleep import summary_for

log = logging.getLogger("cyoa.ai.router")
router = APIRouter(prefix="/api/ai", tags=["ai"])


def _sleep_context(uid: str, settings: UserSettings) -> dict:
    try:
        return ai_context(summary_for(uid, settings), settings.timezone)
    except Exception:
        log.exception("Sleep summary failed; planning without it")
        return {"tracked": False}


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
            events = [e for e in gcal.list_events(user.uid, body.date, settings.timezone) if not e["createdByCyoa"]]
        except gcal.CalendarNotConnected:
            events = []
        except Exception:
            log.exception("Calendar fetch failed; planning without it")

    sleep_ctx = _sleep_context(user.uid, settings)
    windows = meals.meal_windows(settings, body.dayStart, body.dayEnd, sleep_ctx.get("woke_at_local"), body.date)
    try:
        plan, learned = ai.plan_day(
            date=body.date,
            weekday=weekday,
            timezone=settings.timezone,
            priorities=body.priorities,
            day_start=body.dayStart,
            day_end=body.dayEnd,
            goals=_open_goals(user.uid, body.goalIds),
            events=events,
            routes=body.routes,
            sleep=sleep_ctx,
            is_today=body.date == datetime.now(tz(settings.timezone)).date().isoformat(),
            memory=memory.context_for(user.uid, body.date),
            meals=windows,
            meal_notes=settings.mealNotes,
        )
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    added = meals.ensure_meals(plan, windows)  # safety net: every meal is guaranteed
    if added:
        log.info("Meal safety net for %s on %s: %s", user.uid, body.date, "; ".join(added))
    saved = save_day(user.uid, plan, settings)
    memory.record(
        user.uid,
        kind="plan_day",
        day=body.date,
        text=body.priorities or "(planned without stating priorities)",
        learned=learned.learned,
        outdated_ids=learned.outdated_note_ids,
    )
    return saved


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
        ch.options, learned = ai.regenerate_options(
            day=plan,
            chapter=ch,
            goals=_open_goals(user.uid, None),
            hint=body.hint,
            sleep=_sleep_context(user.uid, settings),
            memory=memory.context_for(user.uid, body.date),
            meal_notes=settings.mealNotes,
        )
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    ch.chosenOptionId = None
    saved = save_day(user.uid, plan, settings)
    memory.record(
        user.uid,
        kind="new_options",
        day=body.date,
        text=f'For "{ch.title}": {body.hint}' if body.hint else f'Wanted different options for "{ch.title}"',
        learned=learned.learned,
        outdated_ids=learned.outdated_note_ids,
    )
    return saved


# ---------- what the AI knows about you ----------


@router.get("/memory", response_model=AIMemory)
def get_memory(user: CurrentUser = Depends(current_user)):
    return memory.load(user.uid)


@router.post("/memory/notes", response_model=AIMemory)
def add_memory_note(body: MemoryNoteIn, user: CurrentUser = Depends(current_user)):
    return memory.add_note(user.uid, body.text)


@router.delete("/memory/notes/{note_id}", response_model=AIMemory)
def delete_memory_note(note_id: str, user: CurrentUser = Depends(current_user)):
    return memory.delete_note(user.uid, note_id)


@router.delete("/memory", response_model=AIMemory)
def clear_memory(user: CurrentUser = Depends(current_user)):
    return memory.clear(user.uid)
