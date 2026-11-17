"""Cloud Functions for Firebase entry point (deployed with `firebase deploy`).

- `api`:            the whole FastAPI app as one HTTPS function
- `send_reminders`: runs every minute (Cloud Scheduler) and emails "time to choose" reminders

Local development still uses:  uvicorn app.main:app --reload --port 8000
"""

from a2wsgi import ASGIMiddleware
from firebase_functions import https_fn, options, scheduler_fn

from app.main import app as fastapi_app
from app.notifications import process_due_reminders

# Stored in Google Secret Manager (set by deploy.sh), exposed to the functions as env vars.
SECRETS = ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "SMTP_PASSWORD"]

# Users share their Google Calendar with this account, so the functions run as it.
CALENDAR_SERVICE_ACCOUNT = "firebase-adminsdk-fbsvc@cyoa-f15a9.iam.gserviceaccount.com"

options.set_global_options(region="us-central1", max_instances=10, service_account=CALENDAR_SERVICE_ACCOUNT)

# Created lazily inside the serving worker: a2wsgi starts an event-loop thread, and
# gunicorn imports this module in the parent process before forking workers, where
# that thread would not exist (requests would hang forever).
_wsgi: ASGIMiddleware | None = None


def _get_wsgi() -> ASGIMiddleware:
    global _wsgi
    if _wsgi is None:
        _wsgi = ASGIMiddleware(fastapi_app)
    return _wsgi


def _normalize_path(environ: dict) -> dict:
    """All FastAPI routes live under /api. Whether or not Cloud Functions strips the
    function name from the URL, make sure the app sees exactly one /api prefix."""
    path = environ.get("PATH_INFO") or "/"
    while path.startswith("/api/api"):
        path = path[4:]
    if path != "/api" and not path.startswith("/api/"):
        path = "/api" + (path if path.startswith("/") else "/" + path)
    environ["PATH_INFO"] = path
    return environ


# invoker="public": anyone can reach the URL; every route except /api/health then
# requires a Firebase ID token.
@https_fn.on_request(timeout_sec=300, memory=options.MemoryOption.MB_512, secrets=SECRETS, invoker="public")
def api(req: https_fn.Request) -> https_fn.Response:
    return https_fn.Response.from_app(_get_wsgi(), _normalize_path(req.environ))


@scheduler_fn.on_schedule(schedule="every 1 minutes", timeout_sec=120, secrets=SECRETS)
def send_reminders(event: scheduler_fn.ScheduledEvent) -> None:
    process_due_reminders()
