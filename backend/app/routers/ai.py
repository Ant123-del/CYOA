import logging
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException

from .. import ai, memory, patience, plan_jobs, revise
from ..auth import CurrentUser, current_user, get_user_settings
from ..models import AIMemory, ChapterOptionsIn, DayPlan, MemoryNoteIn, PlanDayIn, ReviseIn
from .days import load_day, save_day

log = logging.getLogger("cyoa.ai.router")
router = APIRouter(prefix="/api/ai", tags=["ai"])


# Shared with the background job runner.
_sleep_context = plan_jobs.sleep_context
_open_goals = plan_jobs.open_goals


@router.post("/plan-day")
def plan_day(body: PlanDayIn, user: CurrentUser = Depends(current_user)):
    """Start planning a day in the background. Returns a job to poll; the user may leave
    the page and will be emailed when the plan is ready."""
    get_user_settings(user)  # ensure the user doc exists
    try:
        date_cls.fromisoformat(body.date)
    except ValueError as exc:
        raise HTTPException(400, "Date must be YYYY-MM-DD") from exc
    if len(body.priorities) > 4000:
        raise HTTPException(400, "Priorities are too long")
    return plan_jobs.create_job(user.uid, body)


@router.get("/plan-jobs")
def active_plan_job(date: str, user: CurrentUser = Depends(current_user)):
    """The unfinished planning job for a day, if any (so a returning user sees progress)."""
    return plan_jobs.active_job(user.uid, date)


@router.get("/plan-jobs/{job_id}")
def get_plan_job(job_id: str, user: CurrentUser = Depends(current_user)):
    job = plan_jobs.get_job(user.uid, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/revise")
def revise_day(body: ReviseIn, user: CurrentUser = Depends(current_user)):
    """Feedback on an existing day ("commute is ~10 min") -> small AI edits + a reply.
    Optionally only one timeline, or rewrite one timeline from scratch."""
    settings = get_user_settings(user)
    plan = load_day(user.uid, body.date)
    if not plan:
        raise HTTPException(404, "No plan for this day")
    try:
        plan, reply, applied, learned = revise.revise(
            plan=plan,
            settings=settings,
            feedback=body.feedback,
            timeline_id=body.timelineId,
            rewrite=body.rewrite,
            memory_ctx=memory.context_for(user.uid, body.date),
            sleep_ctx=_sleep_context(user.uid, settings),
        )
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    saved = save_day(user.uid, plan, settings)
    patience.charge_revision(user.uid, settings)  # each revision costs a point
    memory.record(
        user.uid,
        kind="revise",
        day=body.date,
        text=body.feedback,
        learned=learned.learned,
        outdated_ids=learned.outdated_note_ids,
    )
    return {"plan": saved, "reply": reply, "applied": applied}


@router.post("/plan-jobs/{job_id}/run")
def run_plan_job(job_id: str, user: CurrentUser = Depends(current_user)):
    """Do the planning now. The page fires this and keeps polling; it's fine if the
    person leaves - the job finishes, and the sweeper rescues it if it was cut off."""
    job = plan_jobs.start_job(user.uid, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/plan-jobs/{job_id}/email")
def email_when_ready(job_id: str, user: CurrentUser = Depends(current_user)):
    """'Email me when it's ready' - the user is leaving the page."""
    job = plan_jobs.request_email(user.uid, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


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
