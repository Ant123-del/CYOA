from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user, get_user_settings
from ..firebase import user_ref
from ..models import DayPlan, UserSettings, UserSettingsPatch
from ..notifications import chapter_email, send_email
from ..timeutil import new_id

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=UserSettings)
def get_me(user: CurrentUser = Depends(current_user)):
    return get_user_settings(user)


@router.patch("/me", response_model=UserSettings)
def patch_me(patch: UserSettingsPatch, user: CurrentUser = Depends(current_user)):
    get_user_settings(user)  # ensure the doc exists
    if patch.timezone is not None:
        try:
            ZoneInfo(patch.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(400, "Unknown timezone") from exc
    if patch.notifyEmail is not None:
        if not (user.email_verified and patch.notifyEmail.strip().lower() == user.email.lower()):
            raise HTTPException(400, "Reminders can only be sent to your own verified sign-in email.")
        patch.notifyEmail = user.email
    user_ref(user.uid).set(patch.model_dump(exclude_none=True), merge=True)
    return get_user_settings(user)


@router.post("/notifications/test")
def test_email(user: CurrentUser = Depends(current_user)):
    settings = get_user_settings(user)
    from ..models import Chapter, Option

    demo = DayPlan(
        date="2026-01-01",
        chapters=[
            Chapter(
                id=new_id(),
                start="09:00",
                end="10:00",
                title="Team standup (test email)",
                source="calendar",
                options=[
                    Option(id="a", kind="yes", title="Attend standup", detail="Go as planned."),
                    Option(id="b", kind="yes_and", title="Attend + share demo", detail="Show yesterday's progress."),
                    Option(id="c", kind="no", title="Skip, write async update", detail="Post notes in the channel."),
                    Option(id="d", kind="no_and", title="Skip, update + deep work", detail="Async update, then focus block."),
                ],
            )
        ],
    )
    to = user.email if user.email_verified else ""
    if not to:
        raise HTTPException(400, "Your account has no verified email.")
    try:
        send_email(to, *chapter_email(demo, demo.chapters[0]))
    except Exception as exc:
        raise HTTPException(502, f"Email failed: {exc}") from exc
    return {"sentTo": to}
