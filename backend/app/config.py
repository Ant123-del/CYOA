from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    # Google OAuth client (Web application) used for Google Calendar access
    google_client_id: str = ""
    google_client_secret: str = ""

    # Claude
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

    @field_validator("anthropic_api_key", "google_client_secret", "smtp_password")
    @classmethod
    def _placeholder_is_empty(cls, v: str) -> str:
        # deploy.sh stores "unset" in Secret Manager for empty secrets (it can't store "").
        return "" if v.strip() == "unset" else v.strip()

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

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.backend_url.rstrip('/')}/api/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
