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
SECRETS = ["ANTHROPIC_API_KEY", "GOOGLE_CLIENT_SECRET", "SMTP_PASSWORD"]

options.set_global_options(region="us-central1", max_instances=10)

_wsgi = ASGIMiddleware(fastapi_app)


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


@https_fn.on_request(timeout_sec=300, memory=options.MemoryOption.MB_512, secrets=SECRETS)
def api(req: https_fn.Request) -> https_fn.Response:
    return https_fn.Response.from_app(_wsgi, _normalize_path(req.environ))


@scheduler_fn.on_schedule(schedule="every 1 minutes", timeout_sec=120, secrets=SECRETS)
def send_reminders(event: scheduler_fn.ScheduledEvent) -> None:
    process_due_reminders()
