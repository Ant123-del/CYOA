from dataclasses import dataclass

from fastapi import Header, HTTPException
from firebase_admin import auth as fb_auth

from .firebase import init_firebase, user_ref
from .models import UserSettings


@dataclass
class CurrentUser:
    uid: str
    email: str
    name: str
    email_verified: bool = False


def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """Verify the Firebase ID token sent as `Authorization: Bearer <token>`."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    init_firebase()
    try:
        decoded = fb_auth.verify_id_token(authorization.split(" ", 1)[1])
    except Exception as exc:  # invalid / expired / revoked
        raise HTTPException(401, f"Invalid token: {exc}") from exc
    return CurrentUser(
        uid=decoded["uid"],
        email=decoded.get("email", ""),
        name=decoded.get("name", ""),
        email_verified=bool(decoded.get("email_verified")),
    )


def get_user_settings(user: CurrentUser) -> UserSettings:
    """Load settings, creating the user document with defaults on first use."""
    ref = user_ref(user.uid)
    snap = ref.get()
    if not snap.exists:
        settings = UserSettings(email=user.email, displayName=user.name, notifyEmail=user.email)
        ref.set(settings.model_dump())
        return settings
    return UserSettings(**{**UserSettings().model_dump(), **(snap.to_dict() or {})})


def load_settings_by_uid(uid: str) -> UserSettings | None:
    snap = user_ref(uid).get()
    if not snap.exists:
        return None
    return UserSettings(**{**UserSettings().model_dump(), **(snap.to_dict() or {})})
