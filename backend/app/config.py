from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Local dev reads backend/.env.local. In Cloud Functions, values come from real env vars
    # (.env.cyoa-f15a9 + Secret Manager) and .env.local is not uploaded.
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env.local", extra="ignore")

    # Firebase Admin service account (path relative to backend/). If the file doesn't exist
    # (e.g. in Cloud Functions) the runtime's default credentials are used instead.
    service_account_file: str = "serviceAccountKey.json"

    # Comma-separated list allowed; the first entry is used for links and redirects.
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"

    # The address users share their Google Calendar with. Defaults to the key file's client_email.
    calendar_service_account: str = ""

    # AI: Gemini is used when GEMINI_API_KEY is set, otherwise Claude.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"

    # Outgoing email (reminders). If smtp_host is empty, emails are logged instead.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    enable_scheduler: bool = True

    @field_validator("gemini_api_key", "anthropic_api_key", "smtp_password")
    @classmethod
    def _placeholder_is_empty(cls, v: str, info: ValidationInfo) -> str:
        # deploy.sh stores "unset" in Secret Manager for empty secrets (it can't store "").
        v = "" if v.strip() == "unset" else v.strip()
        # Google shows App Passwords as "abcd efgh ijkl mnop"; the real password has no spaces.
        return v.replace(" ", "") if info.field_name == "smtp_password" else v

    @property
    def service_account_path(self) -> Path:
        p = Path(self.service_account_file)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def frontend_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_url.split(",") if o.strip()]

    @property
    def app_url(self) -> str:
        """Primary frontend URL (for email links and OAuth redirects back to the app)."""
        return self.frontend_origins[0] if self.frontend_origins else "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
