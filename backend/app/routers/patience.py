from fastapi import APIRouter, Depends, HTTPException

from .. import patience
from ..auth import CurrentUser, current_user, get_user_settings
from ..firebase import user_ref
from ..models import PatienceLogIn, PatienceSuggestion, PatienceSummary, PatienceTaskIn, TagPatience
from .days import _find, load_day

router = APIRouter(prefix="/api/patience", tags=["patience"])


@router.get("", response_model=PatienceSummary)
def get_patience(user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    patience.sync_sleep(user.uid, settings)
    return patience.summary(user.uid, settings)


@router.post("/open", response_model=PatienceSummary)
def open_app(user: CurrentUser = Depends(current_user)):
    """Called when the app is opened or brought back to the front: costs a point."""
    settings = get_user_settings(user)
    patience.check_app(user.uid, settings)
    patience.sync_sleep(user.uid, settings)
    return patience.summary(user.uid, settings)


def _task(uid: str, date: str, chapter_id: str, option_id: str):
    plan = load_day(uid, date)
    if not plan:
        raise HTTPException(404, "No plan for this day")
    ch = _find(plan, chapter_id)
    opt = next((o for o in ch.options if o.id == option_id), None)
    if not opt:
        raise HTTPException(404, "Option not found")
    return plan, ch, opt


@router.get("/suggest", response_model=PatienceSuggestion)
def suggest(date: str, chapterId: str, optionId: str, minutes: int | None = None, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    _, ch, opt = _task(user.uid, date, chapterId, optionId)
    return patience.suggest(user.uid, settings, ch, opt, minutes)


@router.post("/tasks", response_model=PatienceSummary)
def record_task(body: PatienceTaskIn, user: CurrentUser = Depends(current_user)):
    """The check-in before a task (expected) or after it (actual)."""
    settings = get_user_settings(user)
    plan, ch, opt = _task(user.uid, body.date, body.chapterId, body.optionId)
    patience.record_task(user.uid, settings, plan, ch, opt, body.phase, body.amount, body.minutes)
    return patience.summary(user.uid, settings)


@router.post("/log", response_model=PatienceSummary)
def log(body: PatienceLogIn, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    patience.log_entry(user.uid, settings, body.label.strip(), body.amount, body.tags, body.minutes)
    return patience.summary(user.uid, settings)


@router.delete("/entries/{entry_id}", response_model=PatienceSummary)
def delete_entry(entry_id: str, user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    if not patience.delete_entry(user.uid, settings, entry_id):
        raise HTTPException(400, "Only things you logged or checked in on can be removed.")
    return patience.summary(user.uid, settings)


@router.put("/tags", response_model=dict[str, TagPatience])
def set_tags(tags: dict[str, TagPatience], user: CurrentUser = Depends(current_user)):
    """Replace every tag's default patience (set on the Board)."""
    if len(tags) > 200 or any(not t.strip() or len(t) > 40 for t in tags):
        raise HTTPException(400, "Tag names must be 1-40 characters.")
    get_user_settings(user)
    data = {t.strip(): p.model_dump() for t, p in tags.items()}
    user_ref(user.uid).update({"patienceTags": data})
    return data
